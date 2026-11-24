// The application's words. People who use it read drilling reports; they do not know what a lane or a frame is,
// so nothing here names the system's parts.
import type { AnswerOut, Citation } from "../api/types";

/** The answer as a headline: the values with their units, or what happened instead. */
export function headline(answer: AnswerOut): string {
  if (answer.status === "answered" && answer.answers.length > 0) {
    return answer.answers.map((a) => (a.unit ? `${a.value} ${a.unit}` : a.value)).join(", ");
  }
  if (answer.status === "not_found_in_graph") return "Not in the knowledge graph";
  if (answer.status === "not_stated") return "The reports do not state this";
  return "No reliable answer";
}

/** What to do next when there is no answer. */
export function advice(answer: AnswerOut): string | null {
  if (answer.status === "answered") return null;
  if (answer.status === "not_found_in_graph") {
    return "Turn off “Graph answers only” to search the report text as well. The closest passages are on the right.";
  }
  if (answer.status === "not_stated") {
    return "The closest passages are on the right. Try naming the well, a date, or the exact quantity.";
  }
  return "The model’s answer could not be checked against the reports, so it is not shown.";
}

/** One sentence on where the answer came from. */
export function basis(answer: AnswerOut): string {
  const computed = answer.evidence.computed;
  if (computed) {
    const days = new Set(computed.events.map((e) => e.date)).size;
    const count = computed.events.length;
    return `Computed from ${count} ${count === 1 ? "operation" : "operations"} on ${days} report ${days === 1 ? "day" : "days"}. No model wrote this number.`;
  }
  if (answer.status === "not_found_in_graph") return "No stored fact or daily operation answers this.";
  if (answer.lanes.length === 0) return "Nothing matched in the reports loaded here.";
  const reports = answer.answered_from === "daily" ? "daily drilling reports" : "end-of-well reports";
  const fellBack = answer.fallback ? " The daily operations held no match, so the report text was searched instead." : "";
  if (answer.lanes.includes("well_facts") && answer.lanes.includes("passages")) {
    return `Written by the model from the well’s checked facts and passages of the ${reports}.${fellBack}`;
  }
  if (answer.lanes.includes("well_facts")) return "Written by the model from the well’s checked facts only.";
  return `Written by the model from passages of the ${reports}.${fellBack}`;
}

/** How a citation was checked, in plain words. */
export function checked(citation: Citation): string {
  switch (citation.how) {
    case "model":
      return "The model cited this passage and its quote is there";
    case "by_quote":
      return "Found by the quote the model gave";
    case "by_value":
      return "Found by the value: the model’s own citation did not hold it";
    case "event_graph":
      return "Holds operations the result was computed from";
    default:
      return "No passage supports this";
  }
}

/** A report's name for display: its ID without the hash a file name carries. */
export function reportName(fileId: string): string {
  return fileId.replace(/-[0-9a-f]{8}$/, "").replace(/^gdr\d+[-_]/, "").replace(/[_-]+/g, " ");
}

/** One step of how a question was answered. The three steps are a sequence, so they are shown numbered. */
export interface Step {
  title: string;
  detail: string;
}

const KIND: Record<AnswerOut["frame"]["kind"], string> = {
  lookup: "A value from an end-of-well report",
  lookup_by_date: "What a daily report says for one day",
  across_wells: "A comparison across several wells",
  over_time: "A total over the daily operations",
  reasoning: "A question about causes",
  other: "A general question about the reports",
};

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** How the question was answered, as the steps the system took: what it understood, what it read, who answered. */
export function trail(answer: AnswerOut): Step[] {
  const { computed, facts, passages } = answer.evidence;
  let read = "Nothing in the loaded reports matched";
  if (computed) {
    const days = new Set(computed.events.map((e) => e.date)).size;
    read = `${count(computed.events.length, "daily operation", "daily operations")} on ${count(days, "report day", "report days")}`;
  } else if (answer.lanes.length > 0) {
    const pieces = [
      facts.length > 0 ? count(facts.length, "checked fact", "checked facts") : "",
      passages.length > 0 ? count(passages.length, "passage", "passages") : "",
    ].filter(Boolean);
    read = pieces.join(" and ") + (answer.fallback ? ", after the daily operations held no match" : "");
  }
  let answered = "No answer was given";
  if (computed) answered = "Calculated in code. No model wrote the number";
  else if (answer.status === "answered") {
    answered = answer.checks.citations_supported
      ? "Written by the model, then each value was found in a passage"
      : "Written by the model. A value has no passage that supports it";
  } else if (answer.status === "not_stated") answered = "The model found no answer in what it read";
  return [
    { title: "Understood as", detail: KIND[answer.frame.kind] },
    { title: "Read", detail: read },
    { title: "Answered", detail: answered },
  ];
}

/** What the answer cost, for the people who watch efficiency. */
export function cost(answer: AnswerOut): string {
  const seconds = answer.cost.seconds < 10 ? answer.cost.seconds.toFixed(1) : Math.round(answer.cost.seconds).toString();
  return `${count(answer.cost.calls, "model call", "model calls")}, ${seconds} s`;
}
