import { describe, expect, it } from "vitest";
import cause from "../../../backend/fixtures/question_cause.json";
import causeWhich from "../../../backend/fixtures/question_cause_which.json";
import endOfWell from "../../../backend/fixtures/question_end_of_well.json";
import notFound from "../../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../../backend/fixtures/question_over_time.json";
import adminQuestions from "../../../backend/fixtures/admin_questions.json";
import well from "../../../backend/fixtures/well.json";
import { exampleApi, exampleEvents, exampleFor, exampleQuestions } from "../api/examples";
import type { AnswerOut, EventOut, LoggedQuestion, WellOut } from "../api/types";
import { aroundEvent, causeSource, citedLabels, gathered, passageChunk, questionDate, reask, reasoningOf } from "./cause";
import { highlight, readable } from "./highlight";
import { HOME, readRoute, routeSearch } from "./route";
import { dayStrips } from "./strips";
import { anyPlanned, casingRows, wholeDays } from "./well";
import {
  advice, askedAt, badge, causePlace, choiceLabel, citedReports, countTiles, dateSpan, depthLabel, distinctSources,
  documentSize, EXPLAIN, factLabel, factValue, headline, hiddenNote, kindName, loggedAnswer, loggedBadge, markLabel,
  missingText, noDays, place, problemDepth, problemDescription, problemSize, problemWhen, propertyName, propertyTip,
  removedNote, reportName, showing, sourceNote, steps, summary, technical, wellTotals,
} from "./wording";

const computed = overTime as AnswerOut;
const written = endOfWell as AnswerOut;
const missing = notFound as AnswerOut;
const caused = cause as AnswerOut;
const which = causeWhich as AnswerOut;

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
  it("make every kind of answer reachable", () => {
    expect(exampleFor("How many hours of non-productive time did AK-3 have?", "allow_fallback").evidence.computed).not.toBeNull();
    expect(exampleFor("What total depth did well AK-3 reach?", "allow_fallback").answers[0].value).toBe("1955");
    expect(exampleFor("What total depth did well ZZ-9 reach?", "exact").status).toBe("not_found_in_graph");
    expect(exampleFor("What caused the stuck pipe on AK-3 on 20 August 2016?", "allow_fallback").evidence.reasoning?.problem).not.toBeNull();
    expect(exampleFor("What caused the non-productive time on AK-3?", "allow_fallback").status).toBe("ask_which");
  });

  it("hide the possible factors of the cause example in exact mode, and count them", () => {
    const exact = exampleFor("What caused the stuck pipe on AK-3 on 20 August 2016?", "exact").evidence.reasoning!;
    expect(exact.possible).toEqual([]);
    expect(exact.possible_hidden).toBe(1);
    expect(exact.stated).toHaveLength(1);
  });
});

describe("questions about causes", () => {
  const reasoning = caused.evidence.reasoning!;

  it("are shown as causes only when one problem was found, or several to choose from", () => {
    expect(reasoningOf(caused)).toBe(reasoning);
    expect(reasoningOf(which)).toBe(which.evidence.reasoning);
    expect(reasoningOf(written)).toBeNull();
    // No problem and no choice: the system answered from report text instead, and the ordinary view shows it.
    const none = { ...caused, status: "not_stated", evidence: { ...caused.evidence, reasoning: { ...reasoning, problem: null, candidates: [] } } } as AnswerOut;
    expect(reasoningOf(none)).toBeNull();
  });

  it("read back the activities around the problem, marking the problem's own", () => {
    const { events, passages } = gathered(reasoning);
    expect(events).toHaveLength(25);
    expect(passages.map((p) => p.id)).toEqual(["P1", "P2", "P3"]);
    expect(events.every((e) => e.event !== null)).toBe(true);
    expect(events.filter((e) => e.problem)).toHaveLength(21);
    expect(events[2].event).toMatchObject({
      date: "2016-08-20", start: "17:00", end: "18:00", hours: 1, end_md: 176, code: "STUCK", npt_code: "KICK",
    });
    expect(events[2].event!.description).toMatch(/^Work to free stuck pipe/);
    expect(events[0].event).toMatchObject({ code: "CIRC", npt_code: null, hours: 1.5, end_md: 149 });
    expect(events[17].event!.hours).toBe(0.25);
  });

  it("take each activity's own fields when the answer carries them", () => {
    const item = reasoning.evidence.find((e) => e.kind === "event" && e.activity)!;
    // The line the AI saw is ignored when the fields are there: a line that cannot be read changes nothing.
    const around = aroundEvent({ ...item, text: "not a line the pattern reads" });
    expect(around.event).toMatchObject({ date: "2016-08-20", start: "14:00", end: "15:30", hours: 1.5, end_md: 149, code: "CIRC", npt_code: null });
    expect(around.event).not.toHaveProperty("problem");
    expect(around.event!.chunks).toEqual(item.activity!.chunks);
    expect(around.problem).toBe(false);
    expect(aroundEvent({ ...item, problem: null, activity: { ...item.activity!, problem: true } }).problem).toBe(true);
  });

  it("give a whole description where the line the AI saw cut it short", () => {
    const cut = reasoning.evidence.find((e) => e.activity && !e.text.endsWith(e.activity.description))!;
    expect(aroundEvent(cut).event!.description).toBe(cut.activity!.description);
  });

  it("read the same activities back from the lines when an answer lacks the fields", () => {
    const withFields = gathered(reasoning).events;
    const withoutFields = gathered({ ...reasoning, evidence: reasoning.evidence.map(({ activity: _activity, ...item }) => item) }).events;
    expect(withoutFields.every((e) => e.event !== null)).toBe(true);
    expect(withoutFields.map((e) => e.problem)).toEqual(withFields.map((e) => e.problem));
    const fields = (e: (typeof withFields)[number]) => {
      const { date, start, end, hours, end_md, code, npt_code } = e.event!;
      return { date, start, end, hours, end_md, code, npt_code };
    };
    expect(withoutFields.map(fields)).toEqual(withFields.map(fields));
  });

  it("keep a line they cannot read, as it is", () => {
    const odd = aroundEvent({ id: "E9", kind: "event", chunk: "x#c1", text: "* something else entirely", problem: null });
    expect(odd.event).toBeNull();
    expect(odd.problem).toBe(false);
    expect(aroundEvent({ id: "E9", kind: "event", chunk: "x#c1", text: "* 2016-08-20 0:00-6:00, 6 h, end depth 10 ft, activity DRIL: x" }).problem).toBe(true);
  });

  it("find where each cited cause is written, so it opens like any source", () => {
    const [stated] = reasoning.stated;
    const source = causeSource(caused, reasoning, stated.citations[0]);
    expect(source).toMatchObject({ file_id: "gdr882-ak3-appx-27-6-dailyreportdetailrpt-nocost-f5e766b8", page: null, text: null, how: "model" });
    expect(causePlace(source)).toBe("AK-3 daily drilling report, 20 Aug 2016");
    const p1 = causeSource(caused, reasoning, { evidence: "P1", chunk: "gdr882_ak3_eowr#c0038", how: "by_quote", quote: "permeable zone" });
    expect(p1).toMatchObject({ file_id: "gdr882_ak3_eowr", page: 20, section: "Health, Safety and Environment" });
    expect(p1.text).toMatch(/^AK-3 was completed with one recordable safety incident/);
    expect(causePlace(p1)).toBe("AK-3 end-of-well report, page 20");
    expect(citedLabels(reasoning)).toEqual(new Set(["E3", "E14"]));
  });

  it("take a passage's report from its ID when the passage is not listed", () => {
    const item = { id: "P9", kind: "daily" as const, chunk: "f62efbee00767a3e7:s6:c0", text: "Mud weight 9.1", page: 4 };
    expect(passageChunk(caused, item)).toMatchObject({ file_id: "f62efbee00767a3e7", page: 4, text: "Mud weight 9.1" });
  });

  it("ask again about a chosen problem by writing its date into the question", () => {
    const kick = which.evidence.reasoning!.candidates[3];
    expect(questionDate("2016-08-20")).toBe("20 August 2016");
    expect(reask("What caused the non-productive time on AK-3?", kick)).toBe("What caused the non-productive time on AK-3 on 20 August 2016?");
    expect(reask("why was AK-3 stopped", kick)).toBe("why was AK-3 stopped on 20 August 2016?");
    expect(reask("What caused the problem on AK-3 on 1 September 2016?", kick)).toBe("What caused the problem on AK-3 on 20 August 2016?");
  });

  it("say what was found in plain words", () => {
    expect(headline(caused)).toBe("1 cause stated in the reports");
    expect(headline({ ...caused, evidence: { ...caused.evidence, reasoning: { ...reasoning, stated: [...reasoning.stated, ...reasoning.stated] } } })).toBe("2 causes stated in the reports");
    expect(headline({ ...caused, status: "not_stated", evidence: { ...caused.evidence, reasoning: { ...reasoning, stated: [] } } })).toBe("No report states the cause");
    expect(headline({ ...caused, status: "invalid" })).toBe("No reliable answer");
    expect(headline(which)).toBe("Which problem do you mean?");
    expect(badge(caused)).toMatchObject({ tone: "ai", label: "Written by AI, each cause checked against the reports" });
    expect(badge(which)).toMatchObject({ tone: "choose", label: "Your choice is needed" });
    expect(summary(caused)).toBe("Based on 25 logged activities and 3 passages of report text around the problem.");
    expect(summary(which)).toBe("6 problems in the daily reports fit your question.");
    expect(advice(which)).toBeNull();
    expect(advice({ ...caused, status: "not_stated" })).toBeNull();
    expect(steps(caused).map((s) => s.detail)).toEqual([
      "A question about what caused a problem",
      "25 logged activities and 3 passages of report text around the problem",
      "An AI named the causes; the system kept only those whose quoted words it found in the reports",
    ]);
    expect(steps(which)[2].detail).toBe("Several problems fit, so we ask which one you mean instead of guessing");
  });

  it("describe a problem and its days as a person reads them", () => {
    const [weather, generators, , kick] = which.evidence.reasoning!.candidates;
    expect(problemWhen(kick)).toBe("20 Aug 2016, 17:00 to 23 Aug 2016, 11:00");
    expect(problemWhen(weather)).toBe("13 Aug 2016, the whole day");
    expect(problemSize(kick)).toBe("66 hours over 21 logged activities");
    expect(problemSize(weather)).toBe("24 hours over 1 logged activity");
    expect(problemDepth(kick)).toBe("176 ft");
    expect(problemDepth({ ...kick, depth_ft: [1700, 1725] })).toBe("1,700 to 1,725 ft");
    expect(problemDescription(weather)).toBe("Weather Delay");
    expect(problemDescription(kick)).toMatch(/Rig up pack off to…$/);
    expect(choiceLabel(generators)).toBe("16–17 Aug 2016 · 14 hours · 0 ft");
    expect(dateSpan("2016-08-30", "2016-09-01")).toMatch(/^30 Aug – 1 Sep/);
    expect(dateSpan("2016-12-31", "2017-01-01")).toBe("31 Dec 2016 – 1 Jan 2017");
  });

  it("mention left-out and hidden causes in one line, and only when there are any", () => {
    expect(removedNote({ stated: 0, possible: 0 })).toBeNull();
    expect(removedNote({ stated: 1, possible: 0 })).toBe("1 more cause was left out because no report text supported it.");
    expect(removedNote({ stated: 1, possible: 2 })).toBe("3 more causes were left out because no report text supported them.");
    expect(hiddenNote(0)).toBeNull();
    expect(hiddenNote(2)).toBe("2 possible factors are not shown because “Verified data only” is on.");
    expect(missingText("offset wells")).toBe("Offset wells");
  });

  it("never use the system's own vocabulary", () => {
    const said = [caused, which].flatMap((a) => [headline(a), badge(a).label, badge(a).tip, summary(a), ...steps(a).flatMap((s) => [s.title, s.detail])]).join(" ");
    expect(said).not.toMatch(/\b(lane|frame|graph|chunk|retriev|token|model call|fallback|coordinator|reasoning)/i);
  });
});

const page = well as WellOut;
const SYSTEM_WORDS = /\b(lane|frame|graph|chunk|retriev|token|model call|fallback|coordinator|reasoning|property|qualifier|null)\b/i;

describe("a well's page in plain words", () => {
  it("names each property the way a reader would", () => {
    expect(propertyName("spud_date")).toBe("Spud date");
    expect(propertyName("api_number")).toBe("API well number");
    expect(propertyName("max_measured_temperature")).toBe("Highest measured temperature");
    expect(propertyName("some_new_thing")).toBe("Some new thing");
    expect(propertyTip("spud_date")).toMatch(/drilling of the well began/);
    expect(propertyTip("some_new_thing")).toBeNull();
  });

  it("says which values were planned, and leaves the actual ones plain", () => {
    expect(factLabel({ property: "total_depth", qualifier: "planned" })).toBe("Total depth (planned)");
    expect(factLabel({ property: "total_depth", qualifier: "actual" })).toBe("Total depth");
    expect(factLabel({ property: "api_number", qualifier: "none" })).toBe("API well number");
    expect(factLabel({ property: "projected_formation_temperature", qualifier: "projected" })).toBe("Projected formation temperature");
  });

  it("gives values with their units, dates as dates and numbers with separators", () => {
    expect(factValue({ property: "total_depth", value: "1955", unit: null })).toBe("1,955 ft");
    expect(factValue({ property: "spud_date", value: "2016-08-18", unit: null })).toBe("18 Aug 2016");
    expect(factValue({ property: "inclination", value: "0.5", unit: null })).toBe("0.5°");
    expect(factValue({ property: "max_measured_temperature", value: "186", unit: null })).toBe("186 °F");
    expect(factValue({ property: "spud_to_release_days", value: "1", unit: null })).toBe("1 day");
    expect(factValue({ property: "productive_time", value: "532.5", unit: null })).toBe("532.5 hours");
    expect(factValue({ property: "api_number", value: "50-295-20005-00-00", unit: null })).toBe("50-295-20005-00-00");
    expect(factValue({ property: "casing_grade", value: "K55", unit: null })).toBe("K55");
    expect(factValue({ property: "total_depth", value: "600", unit: "m" })).toBe("600 m");
    expect(depthLabel("1700")).toBe("1,700 ft");
    expect(depthLabel(undefined)).toBe("Depth not given");
  });

  it("puts a well's days and non-productive time in one sentence", () => {
    expect(wellTotals(page.totals)).toBe(
      "27 days of reports, 115 hours of non-productive time: 66 hours KICK, 24 WAIT, 18.5 WOE and 6.5 WOO.",
    );
    expect(wellTotals({ days: 1, npt_hours: 0, npt_hours_by_code: {} })).toBe("1 day of reports, with no non-productive time marked.");
    expect(wellTotals({ days: 3, npt_hours: 1, npt_hours_by_code: { WAIT: 1 } })).toBe("3 days of reports, 1 hour of non-productive time: 1 hour WAIT.");
    expect(wellTotals({ days: 0, npt_hours: 0, npt_hours_by_code: {} })).toBeNull();
  });

  it("says kindly when a well has no daily reports, and when a report's text is not here", () => {
    expect(noDays("56-32", [{ report_type: "end_of_well" }])).toBe(
      "We have no daily reports for 56-32, so there is no day-by-day timeline. What we know about it comes from its end-of-well report.",
    );
    expect(noDays("TG-4", [])).toBe("We have no daily reports for TG-4, so there is no day-by-day timeline.");
    expect(documentSize({ pages: 28 })).toBe("28 pages");
    expect(documentSize({ pages: 0 })).toBe("Its text is not available on this computer");
  });

  it("lays out each casing string with planned beside actual", () => {
    const rows = casingRows(page.facts.casing_strings[0]);
    expect(page.facts.casing_strings.map((c) => c.size_in)).toEqual(["8-5/8", "5-1/2", "4-1/2", "3-1/2"]);
    expect(rows.map((r) => [r.property, r.planned?.value, r.actual?.value])).toEqual([
      ["casing_depth", "40", "40"], ["casing_weight", "28.55", "28.55"], ["casing_grade", "A53B", "A53B"],
    ]);
    expect(casingRows(page.facts.casing_strings[3]).find((r) => r.property === "casing_depth")).toMatchObject({
      planned: { value: "700" }, actual: { value: "1955" },
    });
    expect(anyPlanned(page.facts.casing_strings)).toBe(true);
    expect(anyPlanned([{ size_in: "7", facts: page.facts.casing_strings[0].facts.filter((f) => f.qualifier === "actual") }])).toBe(false);
  });

  it("draws only the days whose activities are all at hand", () => {
    const drawn = wholeDays(exampleEvents(), page.report_days);
    expect([...new Set(drawn.map((e) => e.date))].sort()).toEqual(["2016-08-13", "2016-08-20", "2016-08-21", "2016-08-22"]);
    expect(wholeDays([event({ hours: 24, start: "0:00", end: "0:00" })], [{ ...page.report_days[0], date: "2016-08-20", hours: 24 }])).toHaveLength(1);
    expect(wholeDays([event({ hours: 6 })], [{ ...page.report_days[0], date: "2016-08-20", hours: 24 }])).toHaveLength(0);
  });

  it("never uses the system's own vocabulary", () => {
    const facts = [...page.facts.general, ...page.facts.depths_and_dates, ...page.facts.casing_strings.flatMap((c) => c.facts),
      ...page.facts.readings.flatMap((r) => r.facts)];
    const said = [
      ...facts.flatMap((f) => [factLabel(f), factValue(f), propertyTip(f.property) ?? ""]),
      wellTotals(page.totals) ?? "", noDays("TG-4", page.documents), ...page.documents.map(documentSize),
    ].join(" ");
    expect(said).not.toMatch(SYSTEM_WORDS);
    expect(said).not.toMatch(/_/);
  });
});

describe("the questions people asked, in plain words", () => {
  const [missing4, cause3, total2] = adminQuestions.questions as LoggedQuestion[];

  it("say when, what kind, and how each was marked", () => {
    expect(askedAt("2026-11-21T09:30:00+00:00")).toBe("21 Nov 2026, 09:30 UTC");
    expect(askedAt(null)).toBe("Time not recorded");
    expect(kindName("over_time")).toBe("A total over a period of time");
    expect(kindName(null)).toBe("Kind not recorded");
    expect([markLabel("right"), markLabel("wrong"), markLabel(null)]).toEqual(["Marked right", "Marked wrong", "Not marked"]);
  });

  it("give the answer each got, in a line", () => {
    expect(loggedAnswer(total2)).toBe("115 hours");
    expect(loggedAnswer(cause3)).toBe("Causes stated in the reports");
    expect(loggedAnswer(missing4)).toBe("Not in the verified data");
    expect(loggedAnswer({ ...missing4, status: "ask_which" })).toBe("We asked which problem was meant");
  });

  it("give each the label its answer had, and claim no check that was not kept", () => {
    expect(loggedBadge(total2).label).toBe("Calculated from the reports");
    expect(loggedBadge(cause3).label).toBe("Written by AI, each cause checked against the reports");
    expect(loggedBadge({ ...cause3, status: "not_stated" }).label).toBe("No stated cause found");
    expect(loggedBadge(missing4).label).toBe("No answer found");
    const written = { status: "answered", lanes: ["well_facts", "passages"], answer_text: "1955 ft", fallback: false };
    expect(loggedBadge(written)).toMatchObject({ tone: "unconfirmed", label: "Written by AI" });
    expect(loggedBadge(written).tip).toMatch(/was not saved/);
    expect(loggedBadge(written, { checks: { citations_supported: true } }).label).toBe("Written by AI, checked against the reports");
    expect(loggedBadge(written, { checks: { citations_supported: false } }).label).toBe("Written by AI, not confirmed");
  });

  it("count them for the top of the page, and say which are shown", () => {
    expect(countTiles({ questions: 4, by_status: { answered: 3 }, by_verdict: { right: 2, none: 2 } })).toEqual([
      { label: "Asked", value: 4 }, { label: "Answered", value: 3 }, { label: "Marked right", value: 2 },
      { label: "Marked wrong", value: 0 }, { label: "Not marked", value: 2 },
    ]);
    expect(showing(0, 20, 45)).toBe("Showing 1–20 of 45 questions");
    expect(showing(40, 5, 45)).toBe("Showing 41–45 of 45 questions");
    expect(showing(0, 0, 0)).toBe("No questions match");
  });

  it("name the reports an answer cited, each once", () => {
    expect(citedReports(["gdr882_ak3_eowr#c0010", "gdr882_ak3_eowr#c0011", "f62efbee00767a3e7:s6:c0"])).toEqual([
      "AK-3 end-of-well report", "f62efbee00767a3e7",
    ]);
    expect(citedReports(undefined)).toEqual([]);
  });

  it("never use the system's own vocabulary", () => {
    const said = (adminQuestions.questions as LoggedQuestion[]).flatMap((q) => [loggedAnswer(q), loggedBadge(q).label, loggedBadge(q).tip, kindName(q.kind), markLabel(q.verdict)]).join(" ");
    expect(said).not.toMatch(SYSTEM_WORDS);
  });
});

describe("screens in the address", () => {
  it("read a well, the questions page and one question from the query string", () => {
    expect(readRoute("")).toEqual(HOME);
    expect(readRoute("?q=What+total+depth")).toEqual(HOME);
    expect(readRoute("?well=AK-3")).toEqual({ view: "well", well: "AK-3" });
    expect(readRoute("?view=questions")).toEqual({ view: "questions", question: null });
    expect(readRoute("?view=questions&question=fixture-log-2")).toEqual({ view: "questions", question: "fixture-log-2" });
  });

  it("write them back the same way", () => {
    for (const route of [HOME, { view: "well", well: "56-32" }, { view: "questions", question: null }, { view: "questions", question: "a b" }] as const) {
      expect(readRoute(routeSearch(route))).toEqual(route);
    }
    expect(routeSearch(HOME)).toBe("");
    expect(routeSearch({ view: "well", well: "AK-3" })).toBe("?well=AK-3");
  });
});

describe("example responses for the newer screens", () => {
  it("filter the example questions as the server does, newest first", () => {
    expect(exampleQuestions({}).map((q) => q.id)).toEqual(["fixture-log-4", "fixture-log-3", "fixture-log-2"]);
    expect(exampleQuestions({ verdict: "none" }).map((q) => q.id)).toEqual(["fixture-log-4", "fixture-log-3"]);
    expect(exampleQuestions({ kind: "cause" }).map((q) => q.id)).toEqual(["fixture-log-3"]);
    expect(exampleQuestions({ q: "STUCK" }).map((q) => q.id)).toEqual(["fixture-log-3"]);
    expect(exampleQuestions({ date_from: "2026-11-22", date_to: "2026-11-22" }).map((q) => q.id)).toEqual(["fixture-log-3"]);
  });

  it("count, page, open and export them", async () => {
    const counts = await exampleApi.questionCounts({});
    expect(counts).toMatchObject({ questions: 3, by_status: { answered: 2, not_found_in_graph: 1 }, by_verdict: { right: 1, wrong: 0, none: 2 } });
    expect((await exampleApi.questions({}, 2, 2)).questions.map((q) => q.id)).toEqual(["fixture-log-2"]);
    expect((await exampleApi.question("fixture-log-2")).record).toHaveProperty("cost");
    expect((await exampleApi.question("fixture-log-4")).record).toEqual({});
    const file = await exampleApi.exportQuestions({ verdict: "none" });
    const written = JSON.parse(file.text);
    expect(file.filename).toBe("collected_2026-11-24.json");
    expect(written.status).toMatch(/^COLLECTED/);
    expect(written).not.toHaveProperty("expected_lane");
    expect(written.questions.map((q: { id: string }) => q.id)).toEqual(["fixture-log-3", "fixture-log-4"]);
    expect(written.questions[0]).toMatchObject({ gold: [], kind: "cause" });
  });

  it("hold a page for AK-3 only, and its activities", async () => {
    expect((await exampleApi.well("AK-3")).well_id).toBe("AK-3");
    await expect(exampleApi.well("56-32")).rejects.toThrow(/AK-3 only/);
    expect(await exampleApi.wellEvents("56-32")).toEqual([]);
    const events = exampleEvents();
    expect(new Set(events.map((e) => `${e.date} ${e.start} ${e.code}`)).size).toBe(events.length);
    expect(events.every((e) => !("problem" in e))).toBe(true);
  });
});
