// The API's shapes, taken from the generated description of the contract (npm run types).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AnswerOut = Schemas["AnswerOut"];
export type QuestionIn = Schemas["QuestionIn"];
export type ChunkOut = Schemas["ChunkOut"];
export type Citation = Schemas["Citation"];
export type FactOut = Schemas["FactOut"];
export type EventOut = Schemas["EventOut"];
export type PageOut = Schemas["PageOut"];
export type WellSummary = Schemas["WellSummary"];
export type Health = Schemas["Health"];
export type Reasoning = Schemas["Reasoning"];
export type Problem = Schemas["Problem"];
export type ReasoningEvidence = Schemas["ReasoningEvidence"];
export type Activity = Schemas["Activity"];
export type Cause = Schemas["Cause"];
export type CauseCitation = Schemas["CauseCitation"];
export type Mode = QuestionIn["mode"];
export type Verdict = Schemas["FeedbackIn"]["verdict"];

// A page about one well.
export type WellOut = Schemas["WellOut"];
export type WellFact = Schemas["WellFact"];
export type CasingString = Schemas["CasingString"];
export type Readings = Schemas["Readings"];
export type WellDocument = Schemas["WellDocument"];
export type ReportDay = Schemas["ReportDay"];
export type WellTotals = Schemas["WellTotals"];

// The questions people asked, as the team reads them back.
export type LoggedQuestion = Schemas["LoggedQuestion"];
export type LoggedQuestionDetail = Schemas["LoggedQuestionDetail"];
export type QuestionPage = Schemas["QuestionPage"];
export type QuestionCounts = Schemas["QuestionCounts"];
export type QuestionSetFile = Schemas["QuestionSetFile"];
export type FeedbackRecord = Schemas["FeedbackRecord"];
