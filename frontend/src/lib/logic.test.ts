import { describe, expect, it } from "vitest";
import endOfWell from "../../../backend/fixtures/question_end_of_well.json";
import notFound from "../../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../../backend/fixtures/question_over_time.json";
import { exampleFor } from "../api/examples";
import type { AnswerOut, EventOut } from "../api/types";
import { highlight, readable } from "./highlight";
import { dayStrips } from "./strips";
import { advice, badge, distinctSources, EXPLAIN, headline, place, reportName, sourceNote, steps, summary, technical } from "./wording";

const computed = overTime as AnswerOut;
const written = endOfWell as AnswerOut;
const missing = notFound as AnswerOut;

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
    const days = dayStrips(computed.evidence.computed!.events);
    expect(days).toHaveLength(10);
    expect(days.reduce((sum, d) => sum + d.nonProductiveHours, 0)).toBe(115);
  });
});

describe("the answer in plain words", () => {
  it("gives the values with their units as the headline", () => {
    expect(headline(computed)).toBe("115 hours");
    expect(headline(written)).toBe("1955 ft");
    expect(headline(missing)).toBe("Not in the verified data");
    expect(headline({ ...missing, status: "not_stated" })).toBe("The reports don’t say");
  });

  it("labels how far each kind of answer can be trusted, with an explanation", () => {
    expect(badge(computed)).toMatchObject({ tone: "calculated", label: "Calculated from the reports" });
    expect(badge(computed).tip).toContain("No AI wrote it");
    expect(badge(written)).toMatchObject({ tone: "ai", label: "Written by AI, checked against the reports" });
    const unconfirmed = { ...written, checks: { citations_supported: false, quotes_verbatim: false } };
    expect(badge(unconfirmed)).toMatchObject({ tone: "unconfirmed", label: "Written by AI, not confirmed" });
    expect(badge(unconfirmed).tip).toContain("check the sources yourself");
    expect(badge(missing)).toMatchObject({ tone: "none", label: "No answer found" });
  });

  it("says in one sentence what the answer is based on", () => {
    expect(summary(computed)).toBe("Added up from 28 activities across 10 days of daily reports.");
    expect(summary(written)).toBe("Based on 12 key facts and 5 passages from the end-of-well reports.");
    expect(summary(missing)).toBe("Nothing in the verified data answers this question.");
    expect(summary({ ...missing, status: "not_stated" })).toBe("We searched the reports but found no clear answer.");
  });

  it("says when the activity log had no match and the text was searched instead", () => {
    const searched = { ...written, lanes: ["passages"], fallback: true, answered_from: "daily", evidence: { ...written.evidence, facts: [] } } as AnswerOut;
    expect(summary(searched)).toBe(
      "Based on 5 passages from the daily reports. The daily activity log had no match, so we searched the report text instead.",
    );
  });

  it("says what to try when there is no answer", () => {
    expect(advice(computed)).toBeNull();
    expect(advice(missing)).toBe("Switch off “Verified data only” to search the full report text as well.");
    expect(advice({ ...missing, status: "not_stated" })).toContain("Try naming the well");
  });

  it("explains how the answer was produced in three steps", () => {
    expect(steps(computed)).toEqual([
      { title: "We understood your question as", detail: "A total over a period of time" },
      { title: "We looked at", detail: "28 activities logged over 10 days in the daily reports" },
      { title: "How the answer was produced", detail: "The system added up the numbers itself" },
    ]);
    expect(steps(written).map((s) => s.detail)).toEqual([
      "A single fact about a well",
      "12 key facts and 5 passages of report text",
      "An AI wrote it, and the system confirmed the value in the report text",
    ]);
    expect(steps(missing)[1].detail).toBe("The reports loaded here, but nothing matched");
    expect(steps(missing)[2].detail).toBe("No answer was given, to avoid guessing");
  });

  it("keeps the technical cost in plain units", () => {
    expect(technical({ ...computed, cost: { calls: 1, prompt_tokens: 900, completion_tokens: 60, seconds: 0.42 } })).toBe("1 AI call, 0.4 seconds");
    expect(technical({ ...computed, cost: { calls: 2, prompt_tokens: 900, completion_tokens: 60, seconds: 23.6 } })).toBe("2 AI calls, 24 seconds");
  });

  it("never uses the system's own vocabulary", () => {
    const said = [
      ...[computed, written, missing].flatMap((a) => [headline(a), badge(a).label, badge(a).tip, summary(a), advice(a) ?? "", ...steps(a).flatMap((s) => [s.title, s.detail])]),
      ...Object.values(EXPLAIN),
    ].join(" ");
    expect(said).not.toMatch(/\b(lane|frame|graph|chunk|retriev|token|model call|fallback|coordinator)/i);
  });
});

describe("sources in plain words", () => {
  it("names reports the way a person would", () => {
    expect(reportName("gdr882_ak3_eowr")).toBe("AK-3 end-of-well report");
    expect(reportName("gdr1295_56-32_eowr")).toBe("56-32 end-of-well report");
    expect(reportName("gdr882-ak3-appx-23-5-nonproductivetimerpt-160927-f6b0f3f1")).toBe("AK-3 non-productive time report");
    expect(reportName("gdr882-ak3-appx-27-6-dailyreportdetailrpt-nocost-f5e766b8")).toBe("AK-3 daily drilling report");
    expect(reportName("some_other_file")).toBe("some other file");
    expect(place("gdr882_ak3_eowr", 7)).toBe("AK-3 end-of-well report, page 7");
    expect(place("gdr882_ak3_eowr", null)).toBe("AK-3 end-of-well report");
  });

  it("tells a summary daily report from a detailed one", () => {
    expect(reportName("gdr882-ak3-appx-30-6-dailyreportsummaryrpt-16092-62efbee0")).toBe("AK-3 daily drilling report (summary)");
  });

  it("lists each report or page once, in the order first cited", () => {
    const sources = distinctSources(computed.citations);
    expect(sources.map((c) => place(c.file_id, c.page))).toEqual([
      "AK-3 non-productive time report",
      "AK-3 daily drilling report",
      "AK-3 daily drilling report (summary)",
    ]);
    const pages = [{ file_id: "gdr882_ak3_eowr", page: 7 }, { file_id: "gdr882_ak3_eowr", page: 9 }, { file_id: "gdr882_ak3_eowr", page: 7 }];
    expect(distinctSources(pages)).toHaveLength(2);
  });

  it("says why each source is listed", () => {
    const citation = written.citations[0];
    expect(sourceNote({ ...citation, how: "by_value" })).toBe("Found by matching the answer’s value");
    expect(sourceNote({ ...citation, how: "event_graph" })).toBe("Contains activities used in the calculation");
    expect(sourceNote({ ...citation, how: "model" })).toBe("The AI pointed to this passage");
  });
});

describe("highlighting the answer in report text", () => {
  const hits = (text: string, values: string[]) => highlight(text, values).filter((p) => p.hit).map((p) => p.text);

  it("finds a number as the report writes it", () => {
    expect(hits("drilled to a vertical depth of 1,955 feet in 27 days", ["1955"])).toEqual(["1,955"]);
    expect(hits("Total NPT 115.0 hours", ["115"])).toEqual(["115.0"]);
    expect(hits("15.5 hours of drilling", ["15.5"])).toEqual(["15.5"]);
  });

  it("does not light up part of a longer number", () => {
    expect(hits("depth 11955 ft, 1955.7 ft, 21,955 ft", ["1955"])).toEqual([]);
  });

  it("matches words whatever their case, and ignores values too short to mean anything", () => {
    expect(hits("Drilled by Nabors rig 7", ["nabors"])).toEqual(["Nabors"]);
    expect(hits("3 days on 3 wells", ["3"])).toEqual([]);
  });

  it("keeps the whole text, in order", () => {
    const parts = highlight("to 1,955 feet (planned 1,700)", ["1955", "1700"]);
    expect(parts.map((p) => p.text).join("")).toBe("to 1,955 feet (planned 1,700)");
    expect(parts.filter((p) => p.hit)).toHaveLength(2);
    expect(highlight("no numbers here", ["1955"])).toEqual([{ text: "no numbers here", hit: false }]);
    expect(highlight("text", [])).toEqual([{ text: "text", hit: false }]);
  });

  it("turns a PDF's private bullet symbols into bullets", () => {
    expect(readable(" WGS-84 UTM Zone 3")).toBe("• WGS-84 UTM Zone 3");
    expect(readable("plain text, 1,955 ft")).toBe("plain text, 1,955 ft");
  });
});

describe("example responses", () => {
  it("make all three kinds of answer reachable", () => {
    expect(exampleFor("How many hours of non-productive time did AK-3 have?", "allow_fallback").evidence.computed).not.toBeNull();
    expect(exampleFor("What total depth did well AK-3 reach?", "allow_fallback").answers[0].value).toBe("1955");
    expect(exampleFor("What total depth did well ZZ-9 reach?", "exact").status).toBe("not_found_in_graph");
  });
});
