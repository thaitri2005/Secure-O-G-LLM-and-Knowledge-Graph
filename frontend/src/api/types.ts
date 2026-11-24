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
export type Mode = QuestionIn["mode"];
export type Verdict = Schemas["FeedbackIn"]["verdict"];
