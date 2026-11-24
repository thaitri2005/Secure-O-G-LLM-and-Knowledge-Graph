// Every sentence the application says. Its readers are drilling engineers and managers, not developers: nothing
// here names a part of the system, and anything that needs explaining comes with an explanation to show on hover.
import type { AnswerOut, Citation } from "../api/types";

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The answer as a headline: the values with their units, or what happened instead. */
export function headline(answer: AnswerOut): string {
  if (answer.status === "answered" && answer.answers.length > 0) {
    return answer.answers.map((a) => (a.unit ? `${a.value} ${a.unit}` : a.value)).join(", ");
  }
  if (answer.status === "not_found_in_graph") return "Not in the verified data";
  if (answer.status === "not_stated") return "The reports don’t say";
  return "No reliable answer";
}

/** How much to trust the answer, as a label with an explanation for hover. */
export interface Badge {
  tone: "calculated" | "ai" | "unconfirmed" | "none";
  label: string;
  tip: string;
}

export function badge(answer: AnswerOut): Badge {
  if (answer.evidence.computed) {
    return {
      tone: "calculated",
      label: "Calculated from the reports",
      tip: "This number was added up directly from the activity tables in the daily reports. No AI wrote it, so it cannot be a guess or a typing mistake.",
    };
  }
  if (answer.status === "answered") {
    return answer.checks.citations_supported
      ? {
          tone: "ai",
          label: "Written by AI, checked against the reports",
          tip: "An AI read the report text shown on the right and wrote this answer. The system then confirmed that the value really appears in that text.",
        }
      : {
          tone: "unconfirmed",
          label: "Written by AI, not confirmed",
          tip: "An AI wrote this answer, but the system could not find the value in the report text. Please check the sources yourself before relying on it.",
        };
  }
  return {
    tone: "none",
    label: "No answer found",
    tip: "The system prefers saying it does not know over guessing. The closest report text is shown so you can look for yourself.",
  };
}

/** One friendly sentence on what the answer is based on. */
export function summary(answer: AnswerOut): string {
  const { computed, facts, passages } = answer.evidence;
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
  if (answer.status === "answered") return null;
  if (answer.status === "not_found_in_graph") return "Switch off “Verified data only” to search the full report text as well.";
  if (answer.status === "not_stated") return "Try naming the well, a date, or the exact thing you want to know.";
  return "The AI’s answer could not be confirmed in the reports, so we are not showing it.";
}

/** One step of how the answer was produced. The steps are a sequence, so they are shown numbered. */
export interface Step {
  title: string;
  detail: string;
}

const KIND: Record<AnswerOut["frame"]["kind"], string> = {
  lookup: "A single fact about a well",
  lookup_by_date: "What happened on a particular day",
  across_wells: "A comparison between wells",
  over_time: "A total over a period of time",
  reasoning: "A question about causes",
  other: "A general question about the reports",
};

export function steps(answer: AnswerOut): Step[] {
  const { computed, facts, passages } = answer.evidence;
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

/** Explanations shown on hover, kept in one place so the same term is always explained the same way. */
export const EXPLAIN = {
  verifiedOnly:
    "When this is on, answers come only from numbers and facts the system has already checked in the reports. If it has none, it says so instead of searching the text and letting an AI write an answer.",
  nonProductive:
    "Non-productive time (NPT): hours when the rig was not making progress, for example waiting on weather or fixing a problem. The reports mark these hours themselves.",
  timeline:
    "Each row is one day, from midnight to midnight. A coloured bar is an activity the reports logged. Hover over a bar, or click it, to see what happened.",
  keyFacts:
    "Facts the system has pulled out of the reports in advance, such as depths and dates, and checked against the original text.",
  reportText: "The exact text from the reports. Yellow highlights show where the answer’s value is written.",
  code: "The short activity code the report itself uses for this operation.",
  pageImage:
    "The page as it appears in the original report. The text beside it is what the system read from this page; the part the answer came from is marked in blue.",
  readBy:
    "How the fact was pulled out of the report: from a table by a fixed rule, or by an AI and then checked against the text.",
} as const;

/** The credit the reports' licence asks for, shown with every page image (README, "Data attribution"). */
export const CREDIT = {
  author: "Geothermal Resource Group, Inc.",
  repository: "https://gdr.openei.org",
  licence: "https://creativecommons.org/licenses/by/4.0/",
} as const;
