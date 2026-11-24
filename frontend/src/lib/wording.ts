// Every sentence the application says. Its readers are drilling engineers and managers, not developers: nothing
// here names a part of the system, and anything that needs explaining comes with an explanation to show on hover.
import type { AnswerOut, Citation, Problem, Reasoning } from "../api/types";
import { gathered, reasoningOf } from "./cause";

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The answer as a headline: the values with their units, or what happened instead. */
export function headline(answer: AnswerOut): string {
  const reasoning = reasoningOf(answer);
  if (answer.status === "ask_which") return "Which problem do you mean?";
  if (reasoning && answer.status !== "invalid") {
    const stated = reasoning.stated.length;
    return stated > 0 ? `${count(stated, "cause", "causes")} stated in the reports` : "No report states the cause";
  }
  if (answer.status === "answered" && answer.answers.length > 0) {
    return answer.answers.map((a) => (a.unit ? `${a.value} ${a.unit}` : a.value)).join(", ");
  }
  if (answer.status === "not_found_in_graph") return "Not in the verified data";
  if (answer.status === "not_stated") return "The reports don’t say";
  return "No reliable answer";
}

/** How much to trust the answer, as a label with an explanation for hover. */
export interface Badge {
  tone: "calculated" | "ai" | "unconfirmed" | "none" | "choose";
  label: string;
  tip: string;
}

const BADGES = {
  choose: {
    tone: "choose",
    label: "Your choice is needed",
    tip: "More than one problem in the reports fits your question. Pick the one you mean and we will look into it.",
  },
  causes: {
    tone: "ai",
    label: "Written by AI, each cause checked against the reports",
    tip: "An AI read the activities and report text on the right and named the causes. The system kept only the causes whose quoted words it found in that text.",
  },
  noCause: {
    tone: "none",
    label: "No stated cause found",
    tip: "None of the reports gives a cause for this problem. Anything listed as a possible factor is an idea to check, not a finding.",
  },
  calculated: {
    tone: "calculated",
    label: "Calculated from the reports",
    tip: "This number was added up directly from the activity tables in the daily reports. No AI wrote it, so it cannot be a guess or a typing mistake.",
  },
  checked: {
    tone: "ai",
    label: "Written by AI, checked against the reports",
    tip: "An AI read the report text shown on the right and wrote this answer. The system then confirmed that the value really appears in that text.",
  },
  unconfirmed: {
    tone: "unconfirmed",
    label: "Written by AI, not confirmed",
    tip: "An AI wrote this answer, but the system could not find the value in the report text. Please check the sources yourself before relying on it.",
  },
  none: {
    tone: "none",
    label: "No answer found",
    tip: "The system prefers saying it does not know over guessing. The closest report text is shown so you can look for yourself.",
  },
} as const satisfies Record<string, Badge>;

export function badge(answer: AnswerOut): Badge {
  const reasoning = reasoningOf(answer);
  if (answer.status === "ask_which") return BADGES.choose;
  if (reasoning && answer.status !== "invalid") return reasoning.stated.length > 0 ? BADGES.causes : BADGES.noCause;
  if (answer.evidence.computed) return BADGES.calculated;
  if (answer.status === "answered") return answer.checks.citations_supported ? BADGES.checked : BADGES.unconfirmed;
  return BADGES.none;
}

/** One friendly sentence on what the answer is based on. */
export function summary(answer: AnswerOut): string {
  const { computed, facts, passages } = answer.evidence;
  const reasoning = reasoningOf(answer);
  if (reasoning && answer.status === "ask_which") {
    return `${count(reasoning.candidates.length, "problem", "problems")} in the daily reports fit your question.`;
  }
  if (reasoning) return `Based on ${aroundCounts(reasoning)} around the problem.`;
  if (computed) {
    const days = new Set(computed.events.map((e) => e.date)).size;
    return `Added up from ${count(computed.events.length, "activity", "activities")} across ${count(days, "day", "days")} of daily reports.`;
  }
  if (answer.status === "not_found_in_graph") return "Nothing in the verified data answers this question.";
  if (answer.lanes.length === 0 || answer.status !== "answered") return "We searched the reports but found no clear answer.";
  const reports = answer.answered_from === "daily" ? "daily reports" : "end-of-well reports";
  const pieces = [
    facts.length > 0 ? count(facts.length, "key fact", "key facts") : "",
    passages.length > 0 ? count(passages.length, "passage", "passages") : "",
  ].filter(Boolean);
  const searched = answer.fallback ? " The daily activity log had no match, so we searched the report text instead." : "";
  return `Based on ${pieces.join(" and ")} from the ${reports}.${searched}`;
}

/** What to try next when there is no answer. */
export function advice(answer: AnswerOut): string | null {
  if (answer.status === "answered" || answer.status === "ask_which") return null;
  // A cause answer says itself when no report states a cause.
  if (reasoningOf(answer) && answer.status === "not_stated") return null;
  if (answer.status === "not_found_in_graph") return "Switch off “Verified data only” to search the full report text as well.";
  if (answer.status === "not_stated") return "Try naming the well, a date, or the exact thing you want to know.";
  return "The AI’s answer could not be confirmed in the reports, so we are not showing it.";
}

/** One step of how the answer was produced. The steps are a sequence, so they are shown numbered. */
export interface Step {
  title: string;
  detail: string;
}

/** Each kind of question in plain words. */
export const KIND: Record<AnswerOut["frame"]["kind"], string> = {
  lookup: "A single fact about a well",
  lookup_by_date: "What happened on a particular day",
  across_wells: "A comparison between wells",
  over_time: "A total over a period of time",
  cause: "A question about what caused a problem",
  other: "A general question about the reports",
};

/** What was gathered around a problem: "25 logged activities and 3 passages of report text". */
function aroundCounts(reasoning: Reasoning): string {
  const { events, passages } = gathered(reasoning);
  return [
    events.length > 0 ? count(events.length, "logged activity", "logged activities") : "",
    passages.length > 0 ? `${count(passages.length, "passage", "passages")} of report text` : "",
  ].filter(Boolean).join(" and ") || "nothing";
}

export function steps(answer: AnswerOut): Step[] {
  const { computed, facts, passages } = answer.evidence;
  const reasoning = reasoningOf(answer);
  if (reasoning) {
    const asking = answer.status === "ask_which";
    let produced = "Several problems fit, so we ask which one you mean instead of guessing";
    if (!asking) {
      produced = answer.status === "invalid"
        ? "An AI was asked for the causes, but its reply could not be read, so nothing is shown"
        : "An AI named the causes; the system kept only those whose quoted words it found in the reports";
    }
    return [
      { title: "We understood your question as", detail: KIND[answer.frame.kind] },
      {
        title: "We looked at",
        detail: asking ? "The problems logged in the daily reports" : `${aroundCounts(reasoning)} around the problem`,
      },
      { title: "How the answer was produced", detail: produced },
    ];
  }
  let looked = "The reports loaded here, but nothing matched";
  if (computed) {
    const days = new Set(computed.events.map((e) => e.date)).size;
    looked = `${count(computed.events.length, "activity", "activities")} logged over ${count(days, "day", "days")} in the daily reports`;
  } else if (answer.lanes.length > 0) {
    const pieces = [
      facts.length > 0 ? count(facts.length, "key fact", "key facts") : "",
      passages.length > 0 ? `${count(passages.length, "passage", "passages")} of report text` : "",
    ].filter(Boolean);
    looked = pieces.join(" and ");
  }
  let produced = "No answer was given, to avoid guessing";
  if (computed) produced = "The system added up the numbers itself";
  else if (answer.status === "answered") {
    produced = answer.checks.citations_supported
      ? "An AI wrote it, and the system confirmed the value in the report text"
      : "An AI wrote it, but the value could not be confirmed in the report text";
  } else if (answer.status === "not_stated") produced = "The AI found no answer in what it read";
  return [
    { title: "We understood your question as", detail: KIND[answer.frame.kind] },
    { title: "We looked at", detail: looked },
    { title: "How the answer was produced", detail: produced },
  ];
}

/** For the curious and for the project team: what the answer cost. */
export function technical(answer: AnswerOut): string {
  const seconds = answer.cost.seconds < 10 ? answer.cost.seconds.toFixed(1) : Math.round(answer.cost.seconds).toString();
  return `${count(answer.cost.calls, "AI call", "AI calls")}, ${seconds} seconds`;
}

/** Why a source is listed, in plain words. */
export function sourceNote(citation: Citation): string {
  switch (citation.how) {
    case "model":
      return "The AI pointed to this passage";
    case "by_quote":
      return "Found by the sentence the AI quoted";
    case "by_value":
      return "Found by matching the answer’s value";
    case "event_graph":
      return "Contains activities used in the calculation";
    default:
      return "Could not be confirmed";
  }
}

const KINDS_OF_REPORT: [RegExp, string][] = [
  [/nonproductivetime/i, "non-productive time report"],
  [/dailyreportsummary/i, "daily drilling report (summary)"],
  [/dailyreport/i, "daily drilling report"],
  [/eowr/i, "end-of-well report"],
];

/** A report's name as a person would say it: "AK-3 end-of-well report", not a file name. */
export function reportName(fileId: string): string {
  const kind = KINDS_OF_REPORT.find(([pattern]) => pattern.test(fileId))?.[1];
  const well = /ak-?3/i.test(fileId) ? "AK-3" : (fileId.match(/\d{1,3}-\d{1,3}/)?.[0] ?? null);
  if (kind) return `${well ? `${well} ` : ""}${kind}`;
  return fileId.replace(/-[0-9a-f]{8}$/, "").replace(/^gdr\d+[-_]/, "").replace(/[_-]+/g, " ");
}

/**
 * The sources to list under an answer: each place once. A calculated total can rest on dozens of passages of the
 * same few reports, and a list that repeats one report's name tells the reader nothing.
 */
export function distinctSources<T extends { file_id: string; page: number | null }>(citations: T[]): T[] {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const where = place(citation.file_id, citation.page);
    if (seen.has(where)) return false;
    seen.add(where);
    return true;
  });
}

/** Where a passage is, as a person would say it. */
export function place(fileId: string, page: number | null): string {
  return `${reportName(fileId)}${page === null ? "" : `, page ${page}`}`;
}

// ---- questions about causes ----

/** A date as a person reads it: "20 Aug 2016". */
export function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** The days a problem lasted: "13 Aug 2016", "20–23 Aug 2016", "31 Aug – 2 Sept 2016". */
export function dateSpan(from: string, to: string): string {
  if (from === to) return longDate(from);
  const [first, last] = [longDate(from), longDate(to)];
  if (from.slice(0, 7) === to.slice(0, 7)) return `${first.split(" ")[0]}–${last}`;
  return from.slice(0, 4) === to.slice(0, 4) ? `${first.replace(/ \d{4}$/, "")} – ${last}` : `${first} – ${last}`;
}

/** When a problem happened, to the hour. */
export function problemWhen(problem: Problem): string {
  if (problem.date_from === problem.date_to) {
    const whole = problem.start === problem.end && problem.hours >= 24;
    return `${longDate(problem.date_from)}, ${whole ? "the whole day" : `${problem.start} to ${problem.end}`}`;
  }
  return `${longDate(problem.date_from)}, ${problem.start} to ${longDate(problem.date_to)}, ${problem.end}`;
}

export function problemSize(problem: Problem): string {
  return `${count(problem.hours, "hour", "hours")} over ${count(problem.events, "logged activity", "logged activities")}`;
}

export function problemDepth(problem: Problem): string {
  const [low, high] = problem.depth_ft.map((ft) => ft.toLocaleString("en-US"));
  return low === high || high === undefined ? `${low} ft` : `${low} to ${high} ft`;
}

/** The report's description of a problem; it arrives cut short, so a cut is shown as one. */
export function problemDescription(problem: Problem): string {
  const text = problem.description.trim();
  return text.length >= 150 && !/[.!?]$/.test(text) ? `${text}…` : text;
}

/** One problem among several, as a choice: "20–23 Aug 2016 · 66 hours · 176 ft". */
export function choiceLabel(problem: Problem): string {
  return `${dateSpan(problem.date_from, problem.date_to)} · ${count(problem.hours, "hour", "hours")} · ${problemDepth(problem)}`;
}

/** Where a cited cause is written: the report and the day for a logged activity, the report and page otherwise. */
export function causePlace(source: { file_id: string; page: number | null; item: { kind: string; date?: string | null } | null }): string {
  if (source.item?.kind === "event" && source.item.date) return `${reportName(source.file_id)}, ${longDate(source.item.date)}`;
  return place(source.file_id, source.page);
}

/** One quiet line when causes were left out because nothing in the reports supported them. */
export function removedNote(removed: Record<string, number>): string | null {
  const total = Object.values(removed).reduce((sum, n) => sum + n, 0);
  if (total === 0) return null;
  return total === 1
    ? "1 more cause was left out because no report text supported it."
    : `${total} more causes were left out because no report text supported them.`;
}

export function hiddenNote(hidden: number): string | null {
  if (hidden === 0) return null;
  return hidden === 1
    ? "1 possible factor is not shown because “Verified data only” is on."
    : `${hidden} possible factors are not shown because “Verified data only” is on.`;
}

/** An item of what a real judgement would still need, as a sentence. */
export function missingText(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Explanations shown on hover, kept in one place so the same term is always explained the same way. */
export const EXPLAIN = {
  problemCode: "The short code the daily report itself gives this non-productive time.",
  stated:
    "Causes a report itself gives. Each comes with the words quoted from the report, and the system checked that those words are really there.",
  possible:
    "Things an AI noticed in the activities and report text that might have played a part. No report says they caused the problem: treat them as ideas to check, not as findings.",
  missing:
    "One well's daily and end-of-well reports say what happened and sometimes why. Judging a cause properly usually also needs the records listed here, which these reports do not contain.",
  problemEvents:
    "Activities marked “The problem” are the non-productive time itself. The others were logged just before and after it, for context.",
  verifiedOnly:
    "When this is on, answers come only from numbers and facts the system has already checked in the reports. If it has none, it says so instead of searching the text and letting an AI write an answer.",
  nonProductive:
    "Non-productive time (NPT): hours when the rig was not making progress, for example waiting on weather or fixing a problem. The reports mark these hours themselves.",
  timeline:
    "Each row is one day, from midnight to midnight. A coloured bar is an activity the reports logged. Hover over a bar, or click it, to see what happened. With a keyboard, the arrow keys move from bar to bar.",
  keyFacts:
    "Facts the system has pulled out of the reports in advance, such as depths and dates, and checked against the original text.",
  reportText: "The exact text from the reports. Yellow highlights show where the answer’s value is written.",
  code: "The short activity code the report itself uses for this operation.",
  pageImage:
    "The page as it appears in the original report. The text beside it is what the system read from this page; the part the answer came from is marked in blue.",
  readBy:
    "How the fact was pulled out of the report: from a table by a fixed rule, or by an AI and then checked against the text.",
  nptCodes:
    "The short codes the daily reports themselves give non-productive time, with the hours marked under each.",
  wellFacts:
    "Facts the system has pulled out of this well’s reports in advance and checked against the original text. Click a value to see the page it is written on.",
  casing:
    "A casing string is a run of steel pipe set in the hole and cemented in place. Each is named by its outer diameter in inches, largest first.",
  readings: "Values the reports give at depths in the hole, shallowest first.",
} as const;

// ---- a page about one well ----

/** A property's plain name, its unit when the reports leave it out, and an explanation for terms that need one. */
const PROPERTY: Record<string, { name: string; unit?: string; tip?: string }> = {
  api_number: { name: "API well number", tip: "The number that identifies the well in the American Petroleum Institute’s numbering, as the report writes it." },
  ground_elevation: { name: "Ground elevation", unit: "ft", tip: "The height of the ground at the well above sea level." },
  total_depth: { name: "Total depth", unit: "ft", tip: "How deep the well was drilled, measured along the hole." },
  spud_date: { name: "Spud date", tip: "The day drilling of the well began." },
  rig_release_date: { name: "Rig release date", tip: "The day the drilling rig finished its work on the well and was let go." },
  drilling_days: { name: "Days of drilling work", unit: "days", tip: "Every day of the drilling work, including setting the rig up and taking it down." },
  spud_to_release_days: { name: "Days from spud to rig release", unit: "days" },
  total_rig_time: { name: "Total rig time", unit: "hours" },
  productive_time: { name: "Productive time", unit: "hours", tip: "Hours when the rig was making progress on the well." },
  non_productive_time: { name: "Non-productive time", unit: "hours", tip: EXPLAIN.nonProductive },
  casing_depth: { name: "Setting depth", unit: "ft", tip: "How deep the bottom of the casing string reaches." },
  casing_weight: { name: "Weight", unit: "lb/ft", tip: "The casing’s weight per foot of pipe, which tells its wall thickness." },
  casing_grade: { name: "Steel grade", tip: "The grade of steel the casing is made of, as the report writes it." },
  inclination: { name: "Inclination", unit: "°", tip: "How far the hole leans from vertical, measured by a survey at that depth." },
  max_measured_temperature: { name: "Highest measured temperature", unit: "°F", tip: "The highest temperature measured in the hole, and the depth it was measured at." },
  projected_formation_temperature: {
    name: "Projected formation temperature",
    unit: "°F",
    tip: "The temperature the rock is expected to return to once the cooling of drilling has passed, worked out from measurements.",
  },
};

/** A property's plain name: "spud_date" is "Spud date". */
export function propertyName(property: string): string {
  const named = PROPERTY[property]?.name;
  if (named) return named;
  const words = property.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function propertyTip(property: string): string | null {
  return PROPERTY[property]?.tip ?? null;
}

/** A fact's name with what kind of value it is, when that is not simply what happened: "Total depth (planned)". */
export function factLabel(fact: { property: string; qualifier: string }): string {
  const name = propertyName(fact.property);
  if (fact.qualifier === "actual" || fact.qualifier === "none" || name.toLowerCase().includes(fact.qualifier)) return name;
  return `${name} (${fact.qualifier})`;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const NUMBER = /^-?\d+(\.\d+)?$/;

/** A number as a person reads it: 1955 is "1,955". */
export function number(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 3 });
}

/** A fact's value as a person reads it: "1,955 ft", "18 Aug 2016", "0.5°", "3 days". */
export function factValue(fact: { property: string; value: string; unit?: string | null }): string {
  if (ISO_DATE.test(fact.value)) return longDate(fact.value);
  const unit = fact.unit ?? PROPERTY[fact.property]?.unit ?? null;
  if (!NUMBER.test(fact.value)) return unit ? `${fact.value} ${unit}` : fact.value;
  const shown = number(Number(fact.value));
  if (!unit) return shown;
  if (unit === "°") return `${shown}°`;
  if ((unit === "days" || unit === "hours") && Number(fact.value) === 1) return `${shown} ${unit.slice(0, -1)}`;
  return `${shown} ${unit}`;
}

/** A depth a reading was taken at: "1,700 ft". */
export function depthLabel(depth: string | number | undefined): string {
  if (depth === undefined || depth === "") return "Depth not given";
  return NUMBER.test(String(depth)) ? `${number(Number(depth))} ft` : String(depth);
}

function listed(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** A well's days in one sentence: "27 days of reports, 115 hours of non-productive time: 66 hours KICK, 24 WAIT ...". */
export function wellTotals(totals: { days: number; npt_hours: number; npt_hours_by_code: Record<string, number> }): string | null {
  if (totals.days === 0) return null;
  const days = count(totals.days, "day of reports", "days of reports");
  if (totals.npt_hours === 0) return `${days}, with no non-productive time marked.`;
  const codes = Object.entries(totals.npt_hours_by_code).map(([code, hours], index) =>
    `${index === 0 ? `${number(hours)} ${hours === 1 ? "hour" : "hours"}` : number(hours)} ${code}`);
  const lost = `${number(totals.npt_hours)} ${totals.npt_hours === 1 ? "hour" : "hours"} of non-productive time`;
  return codes.length > 0 ? `${days}, ${lost}: ${listed(codes)}.` : `${days}, ${lost}.`;
}

/** What a well page says when the well has no daily reports. */
export function noDays(wellId: string, documents: { report_type: string | null }[]): string {
  const endOfWell = documents.some((d) => d.report_type === "end_of_well");
  return `We have no daily reports for ${wellId}, so there is no day-by-day timeline.${endOfWell ? " What we know about it comes from its end-of-well report." : ""}`;
}

/** A report's size as a person would say it, or that its text is not here. */
export function documentSize(document: { pages: number }): string {
  return document.pages > 0 ? count(document.pages, "page", "pages") : "Its text is not available on this computer";
}

// ---- the questions people asked (for the team) ----

/** When a question was asked: "21 Nov 2026, 09:30 UTC". Times are shown in UTC, as the date filters count days. */
export function askedAt(iso: string | null): string {
  if (!iso) return "Time not recorded";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const day = when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const time = when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
  return `${day}, ${time} UTC`;
}

export function kindName(kind: string | null): string {
  return (kind && KIND[kind as keyof typeof KIND]) || "Kind not recorded";
}

export function markLabel(verdict: "right" | "wrong" | null): string {
  if (verdict === "right") return "Marked right";
  return verdict === "wrong" ? "Marked wrong" : "Not marked";
}

/** The shape of a logged question these read: what the log keeps of an answer. */
interface Logged {
  status: string | null;
  lanes: string[];
  answer_text: string | null;
  fallback?: boolean | null;
}

/**
 * Why a question could not be answered, from the name the log keeps of what went wrong. The names are the
 * system's own, so they are read here and never shown.
 */
export function failureReason(error: unknown): string {
  if (typeof error !== "string" || !error) return "";
  if (/busy/i.test(error)) return "the system was busy";
  if (/timeout|connect|network|http|protocol|unavailable/i.test(error)) return "the answering service did not respond";
  return "something went wrong on the server";
}

/** The answer a logged question got, in a line. `record` is the full entry, when it has been read. */
export function loggedAnswer(question: Logged, record: Record<string, unknown> = {}): string {
  if (question.status === "error") {
    const why = failureReason(record.error);
    return why ? `Could not be answered: ${why}` : "Could not be answered";
  }
  if (question.answer_text) return question.answer_text;
  if (question.status === "ask_which") return "We asked which problem was meant";
  if (question.lanes.includes("reasoning")) {
    if (question.status === "answered") return "Causes stated in the reports";
    if (question.status === "not_stated") return "No report states the cause";
  }
  if (question.status === "not_found_in_graph") return "Not in the verified data";
  if (question.status === "not_stated") return "The reports don’t say";
  return "No reliable answer";
}

/**
 * How far a logged answer could be trusted, with the same labels the answer had. The log does not keep whether an
 * AI-written value was confirmed in the text; when that is unknown the label says so instead of claiming it.
 */
export function loggedBadge(question: Logged, record: Record<string, unknown> = {}): Badge {
  if (question.status === "ask_which") return BADGES.choose;
  if (question.status === "error") {
    return {
      tone: "none",
      label: "Not answered",
      tip: "Something stopped the system before it could answer: it was busy with other questions, or a service it depends on did not respond. Nothing was shown to the person who asked.",
    };
  }
  if (question.lanes.includes("reasoning") && question.status !== "invalid") {
    return question.status === "answered" ? BADGES.causes : BADGES.noCause;
  }
  if (question.status !== "answered") return BADGES.none;
  if (question.lanes.includes("events") && !question.fallback) return BADGES.calculated;
  const checks = record.checks as { citations_supported?: boolean } | undefined;
  if (checks?.citations_supported === true) return BADGES.checked;
  if (checks?.citations_supported === false) return BADGES.unconfirmed;
  return {
    tone: "unconfirmed",
    label: "Written by AI",
    tip: "An AI wrote this answer. Whether the system confirmed its value in the report text was not saved with the question, so check it against the reports before relying on it.",
  };
}

/** The numbers at the top of the questions page. */
export function countTiles(counts: { questions: number; by_status: Record<string, number>; by_verdict: Record<string, number> }) {
  const failed = counts.by_status.error ?? 0;
  return [
    { label: "Asked", value: counts.questions },
    { label: "Answered", value: counts.by_status.answered ?? 0 },
    // Shown only when there are some, so "asked" less "answered" is not read as "no answer found".
    ...(failed > 0 ? [{ label: "Could not be answered", value: failed }] : []),
    { label: "Marked right", value: counts.by_verdict.right ?? 0 },
    { label: "Marked wrong", value: counts.by_verdict.wrong ?? 0 },
    { label: "Not marked", value: counts.by_verdict.none ?? 0 },
  ];
}

/** "Showing 1–20 of 45". */
export function showing(offset: number, shown: number, total: number, filtered = true): string {
  if (total === 0) return filtered ? "No questions match" : "No questions yet";
  return `Showing ${number(offset + 1)}–${number(offset + shown)} of ${count(total, "question", "questions")}`;
}

/** The reports a logged answer cited, each once, by name. Cited passages are kept as IDs, which start with the report's. */
export function citedReports(chunkIds: unknown): string[] {
  if (!Array.isArray(chunkIds)) return [];
  return [...new Set(chunkIds.filter((id): id is string => typeof id === "string").map((id) => reportName(id.split(/[#:]/)[0])))];
}

/** The credit the reports' licence asks for, shown with every page image (README, "Data attribution"). */
export const CREDIT = {
  author: "Geothermal Resource Group, Inc.",
  repository: "https://gdr.openei.org",
  licence: "https://creativecommons.org/licenses/by/4.0/",
} as const;

// ---- waiting for an answer ----

/** What happens between asking and the answer, in order. Which one is under way is told by the time that has passed. */
export const WAITING_STEPS = [
  { from: 0, title: "Reading your question", detail: "Working out which well, which dates and which numbers you mean." },
  { from: 4, title: "Looking through the reports", detail: "Finding the pages and the logged activities that match." },
  { from: 15, title: "Writing the answer and checking it", detail: "Each value is checked against the report text before you see it." },
] as const;

/** The step under way after this many seconds. */
export function waitingStep(seconds: number): number {
  let current = 0;
  WAITING_STEPS.forEach((step, index) => {
    if (seconds >= step.from) current = index;
  });
  return current;
}

/** Time spent waiting, as a person says it: "8 seconds", "1 minute 5 seconds". */
export function elapsed(seconds: number): string {
  const secs = count(seconds % 60, "second", "seconds");
  if (seconds < 60) return secs;
  return `${count(Math.floor(seconds / 60), "minute", "minutes")} ${secs}`;
}

/** One calm line under the steps; it changes as the wait grows, so a long wait never looks like a fault. */
export function waitingNote(seconds: number): string {
  if (seconds < 40) return "This usually takes less than a minute.";
  if (seconds < 90) return "Still working. A detailed question can take a minute or more.";
  if (seconds < 180) return "This is taking longer than usual. You can keep waiting, or stop and ask again.";
  return "Nearly at the limit. If no answer comes within four minutes, we stop and you can ask again.";
}

export const WAITING = {
  title: "Reading the reports for you",
  stop: "Stop",
  stopped: "Stopped. Your question is still in the box, so you can change it or ask again.",
} as const;

// ---- long lists ----

/** The button that unfolds a long list: "Show all 28 activities". */
export function showAll(total: number, things: string): string {
  return `Show all ${number(total)} ${things}`;
}

/** What a folded list says about itself: "Showing the first 7 of 28 activities." */
export function showingFirst(shown: number, total: number, things: string): string {
  return `Showing the first ${number(shown)} of ${number(total)} ${things}.`;
}

/** The button that folds it again. */
export function showFewer(things: string): string {
  return `Show fewer ${things}`;
}

/** A day's heading in a list of activities: "20 Aug 2016", "24 hours logged", "7 hours non-productive". */
export function dayHours(hours: number): string {
  return `${number(hours)} ${hours === 1 ? "hour" : "hours"}`;
}

// ---- the browser tab ----

export const APP_NAME = "Drilling Reports Assistant";

/** The title of the browser tab, so each screen can be told apart in the history and in a printed page's header. */
export function pageTitle(screen: string | null): string {
  return screen ? `${screen} · ${APP_NAME}` : APP_NAME;
}

/** What a day's heading says of its activities in a list: "4 activities, 8.5 hours". */
export function daySummary(activities: number, hours: number): string {
  return `${count(activities, "activity", "activities")}, ${dayHours(hours)}`;
}

/** The non-productive part of a day, on its heading: "7 hours non-productive". */
export function dayLost(hours: number): string {
  return `${dayHours(hours)} non-productive`;
}

// ---- notices ----

/** Said while the application runs on prepared examples: in full on the start page, in short beside the question box. */
export const DEMO = {
  full: "Demo mode: no AI is connected. The report text and numbers are real; each answer shown is a prepared example.",
  short: "Demo mode: no AI is connected. Each answer is a prepared example.",
} as const;

export const COPY = {
  ask: "Copy link",
  done: "Link copied",
  announced: "A link to this answer was copied.",
  failed: "The link could not be copied here. Copy it from the address bar instead.",
} as const;

/** Under an answer that names no page: said plainly, so the missing list is not taken for an oversight. */
export const NO_SOURCES = "No page of a report was recorded for this answer. Check it against the evidence before relying on it.";

/** What the questions page says when its list is empty. */
export function emptyLog(filtered: boolean): string {
  return filtered
    ? "No question matches these filters. Clear a filter to see more."
    : "Nobody has asked a question yet. Questions asked on the start page appear here, newest first.";
}

/** The link printed under an answer on paper, where nothing can be clicked. */
export const PRINTED_FROM = "Printed from the Drilling Reports Assistant. This answer:";

/** How a logged question ended, as the questions page lets it be chosen. */
export const ENDED: { value: "" | "answered" | "error"; label: string }[] = [
  { value: "", label: "Any" },
  { value: "answered", label: "Answered" },
  { value: "error", label: "Could not be answered" },
];

/** Said on the start page when the server says it cannot answer questions just now. */
export const NOT_READY = "Questions cannot be answered right now: the answering service is not responding. You can still look at the wells and their reports.";
