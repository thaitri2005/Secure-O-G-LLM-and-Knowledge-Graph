# Track B: GraphRAG engine and models

**Owner (first stint, from 30 October 2026):** Tri · **Scope:** [specification §4.5](../../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files) · **Plan:** [M1, Track B](../../DEVELOPMENT_PLAN.md#track-b-graphrag-engine-and-models-first-stint-tri)

This track turns chunks with IDs into a graph and vectors that answer questions with chunk citations. It uses open-weight models of about 7B or smaller (D-37), at a cost per page that is known and kept low.

| File | What it holds |
|---|---|
| [log.md](log.md) | **Every finding, decision, design choice and experiment**, dated and numbered (B-F, B-D, B-C, and E links) |
| [survey.md](survey.md) | Ready-made GraphRAG repositories: what each does, whether to run it, learn from it or skip it, and what to copy |

Measurements go into experiment records in [`docs/experiments/`](../../experiments/README.md) (E14 onward). The log links to them and does not copy their numbers.

## Working rules for this stint

1. **Start small (D-44).**
   - Begin with the 15 AK-3 end-of-well report (EOWR) chunks the prototype used, then move to the whole AK-3 EOWR.
   - Daily drilling reports come only after a base is chosen.
   - Check answers against the prototype's 31 questions and the E10 gold facts.
2. **Efficiency is a headline metric.** Every run records:
   - LLM calls;
   - input and output tokens;
   - wall-clock seconds;
   - cost per page and per question;

   alongside quality. A base that is slightly better but several times more expensive per page loses.
3. **Use what exists, then improve it.** Look only at solutions close to our description, take them over and make them better on drilling reports (B-D08). Copied code keeps its credit ([survey](survey.md#licences)).
4. **Keep everything else fixed when comparing.** Every candidate gets the same chunks, questions, model and token budget, so that the comparison measures the pipeline and not the setup.
5. **Log as you go.** A finding, a decision, a design choice or a run goes into [log.md](log.md) the same day. A decision that changes the specification also goes into specification §13.1.
