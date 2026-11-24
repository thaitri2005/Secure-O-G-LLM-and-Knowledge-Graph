import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import endOfWell from "../../backend/fixtures/question_end_of_well.json";
import well from "../../backend/fixtures/well.json";
import App from "./App";
import { ApiError, type Api } from "./api/client";
import { exampleApi, exampleEvents } from "./api/examples";
import type { AnswerOut, WellOut } from "./api/types";

// The page about one well: what the reports say about it, its reports, and its days.

const AK3 = well as WellOut;

type Fake = Api & { well: ReturnType<typeof vi.fn>; wellEvents: ReturnType<typeof vi.fn>; page: ReturnType<typeof vi.fn> };

function fakeApi(shown: WellOut = AK3): Fake {
  return {
    ...exampleApi,
    ask: vi.fn(async (question: string, mode: string) => ({ ...(endOfWell as AnswerOut), question, mode }) as AnswerOut),
    well: vi.fn(async () => shown),
    wellEvents: vi.fn(async () => exampleEvents()),
    page: vi.fn(exampleApi.page),
  };
}

/** AK-3's page as a well with end-of-well facts and no daily reports would have it. */
const WITHOUT_DAYS: WellOut = {
  ...AK3,
  well_id: "56-32",
  documents: AK3.documents.filter((d) => d.report_type === "end_of_well"),
  report_days: [],
  totals: { days: 0, events: 0, hours: 0, npt_hours: 0, npt_hours_by_code: {} },
};

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.localStorage.setItem("drilling-reports.guide-seen", "1");
  window.history.replaceState(null, "", "/");
});

async function openFromStart(api: Api) {
  render(<App api={api} />);
  const loaded = await screen.findByRole("table", { name: "Wells loaded" });
  const user = userEvent.setup();
  await user.click(within(loaded).getByRole("link", { name: "AK-3" }));
  await screen.findByRole("heading", { name: "Well AK-3" });
  return user;
}

describe("a well's page", () => {
  it("opens from the list of wells on the start page, with its days in one sentence", async () => {
    const api = fakeApi();
    await openFromStart(api);
    expect(api.well).toHaveBeenCalledWith("AK-3");
    expect(window.location.search).toBe("?well=AK-3");
    expect(screen.getByText(/27 days of reports, 115 hours of non-productive time: 66 hours KICK, 24 WAIT, 18.5 WOE and 6.5 WOO\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What is these codes?" })).toBeInTheDocument();
  });

  it("gives what we know in groups, with plain names, units and explanations", async () => {
    await openFromStart(fakeApi());
    const depths = screen.getByRole("table", { name: "Depths and dates" });
    expect(within(depths).getByRole("row", { name: /Total depth \(planned\).*1,700 ft/ })).toBeInTheDocument();
    expect(within(depths).getByRole("row", { name: /^Total depth .*1,955 ft/ })).toBeInTheDocument();
    expect(within(depths).getByRole("row", { name: /Spud date .*18 Aug 2016/ })).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "General" })).getByText("API well number")).toBeInTheDocument();
    const casing = screen.getByRole("table", { name: "Casing strings" });
    expect(within(casing).getAllByRole("row")).toHaveLength(1 + 3 + 3 + 3 + 2);
    expect(within(casing).getByRole("row", { name: /3-1\/2 in Setting depth.*700 ft.*1,955 ft/ })).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Inclination at depths" })).getAllByRole("row")).toHaveLength(19);
    const user = userEvent.setup();
    await user.hover(within(depths).getAllByRole("button", { name: "What is spud date?" })[0]);
    expect(screen.getByRole("tooltip")).toHaveTextContent("The day drilling of the well began.");
    expect(document.body.textContent).not.toMatch(/_|\bnull\b|\bgraph\b|\bchunk/);
  });

  it("opens a fact at the page it is written on, and goes back to the days", async () => {
    const api = fakeApi();
    const user = await openFromStart(api);
    await user.click(screen.getByRole("button", { name: "50-295-20005-00-00: open AK-3 end-of-well report, page 7" }));
    expect(api.page).toHaveBeenCalledWith("gdr882_ak3_eowr", 7);
    expect(await screen.findByRole("heading", { name: "AK-3 end-of-well report, page 7" })).toBeInTheDocument();
    expect(screen.getByAltText("AK-3 end-of-well report, page 7, as printed in the report")).toHaveAttribute("src", "/example-pages/gdr882_ak3_eowr/p7.png");
    expect(screen.getByText("The part the fact came from, as the system read it:")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Day by day" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to the days and reports" }));
    expect(screen.getByRole("heading", { name: "Day by day" })).toBeInTheDocument();
  });

  it("draws the days it has all the activities of, and lists every day with its non-productive hours", async () => {
    const user = await openFromStart(fakeApi());
    expect(within(screen.getByRole("list", { name: "Days" })).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText(/The timeline shows the 4 days whose activities are all at hand/)).toBeInTheDocument();
    const days = within(screen.getByRole("table", { name: "Report days" })).getAllByRole("row");
    expect(days).toHaveLength(28);
    expect(days[2]).toHaveTextContent("13 Aug 2016");
    expect(within(days[2]).getByText("24 h")).toHaveClass("npt");
    expect(within(days[1]).queryByText(/ h$/)).not.toBeInTheDocument();
    // A bar chosen on the timeline marks its day in the list.
    const bar = within(screen.getByRole("list", { name: "Days" })).getAllByRole("button")[0];
    await user.click(bar);
    expect(days[2]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("note", { name: "Selected activity" })).toHaveTextContent("13 Aug, 0:00 to 0:00, 24 hours, non-productive time");
  });

  it("lists its reports, and says when a report's text is not here", async () => {
    await openFromStart(fakeApi());
    const reports = screen.getByRole("region", { name: "Its reports" });
    const items = within(reports).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("AK-3 end-of-well report28 pages");
    expect(items[1]).toHaveTextContent("AK-3 non-productive time reportIts text is not available on this computer");
  });

  it("shows no timeline for a well without daily reports, and says so kindly", async () => {
    const api = fakeApi(WITHOUT_DAYS);
    window.history.replaceState(null, "", "/?well=56-32");
    render(<App api={api} />);
    expect(await screen.findByRole("heading", { name: "Well 56-32" })).toBeInTheDocument();
    expect(screen.getByText(/We have no daily reports for 56-32, so there is no day-by-day timeline\. What we know about it comes from its end-of-well report\./)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Days" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Report days" })).not.toBeInTheDocument();
    expect(api.wellEvents).not.toHaveBeenCalled();
    expect(screen.getByText("No daily reports are loaded for this well.")).toBeInTheDocument();
  });

  it("says what went wrong when the page cannot be read, and tries again", async () => {
    const api = fakeApi();
    api.well.mockRejectedValueOnce(new ApiError("The examples hold a page for AK-3 only."));
    window.history.replaceState(null, "", "/?well=TG-2");
    render(<App api={api} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The examples hold a page for AK-3 only.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Well AK-3" })).toBeInTheDocument();
  });

  it("is reached from a well's name under an answer", async () => {
    render(<App api={fakeApi()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Ask about the reports"), "What total depth did well AK-3 reach?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(await screen.findByRole("tab", { name: /Key facts/ }));
    await user.click(within(screen.getByRole("table", { name: "Key facts" })).getAllByRole("link", { name: "AK-3" })[0]);
    expect(await screen.findByRole("heading", { name: "Well AK-3" })).toBeInTheDocument();
  });
});

describe("moving between screens", () => {
  it("works with the browser's back button, and a copied link opens the same page", async () => {
    await openFromStart(fakeApi());
    expect(screen.queryByRole("table", { name: "Wells loaded" })).not.toBeInTheDocument();
    act(() => {
      window.history.back();
    });
    expect(await screen.findByRole("table", { name: "Wells loaded" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("goes back to the start from a page opened by a link", async () => {
    window.history.replaceState(null, "", "/?well=AK-3");
    render(<App api={fakeApi()} />);
    await screen.findByRole("heading", { name: "Well AK-3" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("table", { name: "Wells loaded" })).toBeInTheDocument();
  });

  it("answers a question asked from a well's page on the main screen", async () => {
    const api = fakeApi();
    const user = await openFromStart(api);
    await user.type(screen.getByLabelText("Ask about the reports"), "What total depth did well AK-3 reach?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("heading", { name: "1955 ft" })).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("explains the well page in the guide", async () => {
    render(<App api={fakeApi()} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "How it works" }));
    expect(within(screen.getByRole("dialog", { name: "How it works" })).getByText(/Click a well’s name to open its page/)).toBeInTheDocument();
  });
});
