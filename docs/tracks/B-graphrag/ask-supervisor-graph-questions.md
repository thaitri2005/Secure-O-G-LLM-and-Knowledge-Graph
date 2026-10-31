# Request to the supervisor: questions where a graph should help

Draft by Track B, 31 October 2026, for Tri to send to anh Tuấn (B-D15 step 1). Translate as needed; keep the technical terms in English.

## Why we ask

- On the prototype's 31 questions, plain RAG (Qwen3-8B, BM25 routed by well, cited answers checked in code) already answers 28/31, on one report and on three ([E18](../../experiments/E18-well-routing.md)). These questions each name one well and ask for one value.
- Two GraphRAG bases built on the same reports do not beat it on these questions: neo4j-graphrag-python ([E16](../../experiments/E16-neo4j-graphrag-python.md)) and LightRAG (E19).
- A graph should earn its cost on questions that **compare or combine several wells or reports**, **count**, or **follow a link** (person, company, well to well). Plain RAG answers at most 3 of our 9 such probe questions (E19).
- A graph of per-well facts, built from table rows by our ontology's mappings and from LLM extraction, then checked in code, raises the single-well questions to 30/31, stable across variants ([E20](../../experiments/E20-well-fact-sheet.md), [E22](../../experiments/E22-table-facts.md)). On our 9 cross-well questions it scores 2 to 5 of 9 depending on small changes, which 9 questions cannot tell from noise. **We need more real questions of this kind (ideally 30 or more) to decide whether the graph is worth its cost.**

## What we would like

1. **Example questions from the expert group, or from you,** of the kinds below, on end-of-well and daily drilling reports. Even 10 to 20 would let us judge the graph fairly.
2. If the expert set is not ready, confirm that our probe questions below are the right kind, so we can extend them.

## Our probe questions (development only, not an evaluation set)

| Kind | Example |
|---|---|
| Comparison | Which of the wells AK-3, 56-32 and 68-32 was drilled deepest? |
| Comparison | Which of these wells were drilled deeper than planned? |
| Across reports | On what dates were wells AK-3, 68-32 and 56-32 spudded? |
| Shared people | Which GRG geologist worked on both AK-3 and the Utah FORGE monitoring wells? |
| Count | How many of the end-of-well reports cover Utah FORGE wells? |
| Well to well | Injection in which well was 68-32 drilled to monitor? |

The file is [`graphrag/gold/cross_report_probe.json`](../../../graphrag/gold/cross_report_probe.json); gold values and source chunks are taken from the three public reports.

## Questions for the meeting

- Are comparison, count and link questions across wells what VPI's users would ask?
- Should daily drilling reports bring time-based questions (for example "how many hours of NPT on well X in the 12-1/4 in. section?")?
- When will the expert question set arrive (Q2 in specification §13.2)?
