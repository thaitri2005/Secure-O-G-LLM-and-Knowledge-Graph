import { describe, expect, it } from "vitest";
import endOfWell from "../../../backend/fixtures/question_end_of_well.json";
import notFound from "../../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../../backend/fixtures/question_over_time.json";
import { exampleFor } from "../api/examples";
import type { AnswerOut, EventOut } from "../api/types";
import { dayStrips } from "./strips";
import { advice, basis, checked, headline, reportName } from "./wording";

const event = (over: Partial<EventOut>): EventOut => ({
  date: "2016-08-20", start: "0:00", end: "6:00", hours: 6, end_md: 100, code: "DRIL", description: "", npt_code: null,
  chunks: [], ...over,
});

describe("day strips", () => {
  it("places each event by its start and its hours", () => {
    const [day] = dayStrips([event({ start: "6:00", end: "12:00", hours: 6 }), event({})]);
    expect(day.segments.map((s) => [s.left, s.width])).toEqual([[0, 25], [25, 25]]);
    expect(day.hours).toBe(12);
  });

  it("draws a whole day written as 0:00 to 0:00 across the strip", () => {
    const [day] = dayStrips([event({ start: "0:00", end: "0:00", hours: 24, npt_code: "KICK" })]);
    expect(day.segments[0]).toMatchObject({ left: 0, width: 100 });
    expect(day.nonProductiveHours).toBe(24);
  });

  it("never draws past the end of the day", () => {
    const [day] = dayStrips([event({ start: "22:00", end: "2:00", hours: 4 })]);
    expect(day.segments[0].left + day.segments[0].width).toBeCloseTo(100);
  });

  it("puts days in date order", () => {
    const days = dayStrips([event({ date: "2016-08-22" }), event({ date: "2016-08-20" }), event({ date: "2016-08-21" })]);
    expect(days.map((d) => d.date)).toEqual(["2016-08-20", "2016-08-21", "2016-08-22"]);
  });

  it("reads the real example: 115 non-productive hours on 10 days", () => {
    const days = dayStrips((overTime as AnswerOut).evidence.computed!.events);
    expect(days).toHaveLength(10);
    expect(days.reduce((sum, d) => sum + d.nonProductiveHours, 0)).toBe(115);
  });
});

describe("wording", () => {
  it("gives the values with their units as the headline", () => {
    expect(headline(overTime as AnswerOut)).toBe("115 hours");
    expect(headline(endOfWell as AnswerOut)).toBe("1955 ft");
  });

  it("says what to do when the graph holds no answer", () => {
    expect(headline(notFound as AnswerOut)).toBe("Not in the knowledge graph");
    expect(advice(notFound as AnswerOut)).toContain("Graph answers only");
    expect(advice(overTime as AnswerOut)).toBeNull();
  });

  it("says a computed number was not written by a model", () => {
    expect(basis(overTime as AnswerOut)).toBe("Computed from 28 operations on 10 report days. No model wrote this number.");
    expect(basis(endOfWell as AnswerOut)).toContain("checked facts and passages of the end-of-well reports");
    expect(basis(notFound as AnswerOut)).toBe("No stored fact or daily operation answers this.");
    expect(basis({ ...(notFound as AnswerOut), status: "not_stated" })).toBe("Nothing matched in the reports loaded here.");
  });

  it("says when the daily operations held no match and text was searched instead", () => {
    const fellBack = { ...(endOfWell as AnswerOut), lanes: ["passages"], fallback: true, answered_from: "daily" } as AnswerOut;
    expect(basis(fellBack)).toBe(
      "Written by the model from passages of the daily drilling reports. The daily operations held no match, so the report text was searched instead.",
    );
  });

  it("explains each way a citation was checked", () => {
    const citation = (endOfWell as AnswerOut).citations[0];
    expect(checked({ ...citation, how: "by_value" })).toContain("did not hold it");
    expect(checked({ ...citation, how: "event_graph" })).toContain("computed from");
  });

  it("shortens report names", () => {
    expect(reportName("gdr882_ak3_eowr")).toBe("ak3 eowr");
    expect(reportName("gdr882-ak3-appx-23-5-nonproductivetimerpt-160927-f6b0f3f1")).toBe("ak3 appx 23 5 nonproductivetimerpt 160927");
  });
});

describe("example responses", () => {
  it("make all three kinds of answer reachable", () => {
    expect(exampleFor("How many hours of non-productive time did AK-3 have?", "allow_fallback").status).toBe("answered");
    expect(exampleFor("How many hours of non-productive time did AK-3 have?", "allow_fallback").evidence.computed).not.toBeNull();
    expect(exampleFor("What total depth did well AK-3 reach?", "allow_fallback").answers[0].value).toBe("1955");
    expect(exampleFor("What total depth did well ZZ-9 reach?", "exact").status).toBe("not_found_in_graph");
  });
});
