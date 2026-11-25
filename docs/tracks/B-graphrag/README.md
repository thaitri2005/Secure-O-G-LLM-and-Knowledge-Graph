# Track B: GraphRAG engine and models

**Owner (first stint, from 30 October 2026):** Tri · **Scope:** [specification §4.5](../../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files) · **Plan:** [M1, Track B](../../DEVELOPMENT_PLAN.md#m1-how-the-first-build-closed)

This track turns chunks with IDs into a graph and vectors that answer questions with chunk citations. It uses open-weight models of about 7B or smaller (D-37), at a cost per page that is known and kept low.

| File | What it holds |
|---|---|
| [log.md](log.md) | **Every finding, decision, design choice and experiment**, dated and numbered (B-F, B-D, B-C, and E links) |
| [survey.md](survey.md) | Ready-made GraphRAG repositories: what each does, whether to run it, learn from it or skip it, and what to copy |
| [next-runs.md](next-runs.md) | Commands to reproduce the runs, and what Track B is waiting on |
| [note-for-track-A-daily-reports.md](note-for-track-A-daily-reports.md) | What Track B needs from K1 version 1 |
| [Stint reports](../../reports/stints/README.md) | What each stint accomplished, for the supervisor: [10 to 27 November](../../reports/stints/STINT_REPORT_2026-11-27.md), and Tri's [5 November update](../../reports/stints/STINT_UPDATE_2026-11-05.md), in Vietnamese |
| [plan-lanes-and-coordinator.md](plan-lanes-and-coordinator.md) | The implementation plan for the lanes and the coordinator, carried out on 24 November |
| [plan-production-readiness.md](plan-production-readiness.md) | How the build of 24 November was split into work packages across the three tracks, carried out the same day (B-D41) |
| Notes to teammates, 24 November | [for Khai](../A-ingestion/note-from-track-B-2026-11-24.md) and [for Hung](../C-storage/note-from-track-B-2026-11-24.md): what was built in their tracks with their clearance, and what is left for each |
| [ask-supervisor-graph-questions.md](ask-supervisor-graph-questions.md) | The 31 October request for graph-worthy questions (historical) |

**Where things stand on 25 November 2026:** the log's "Current state" table. The second build is coded and runs end to end with the real model, as containers on the stores: the coordinator and four lanes ([specification §8.1](../../PROJECT_DESIGN.md#81-the-coordinator-and-its-lanes), [§8.6](../../PROJECT_DESIGN.md#86-reasoning-about-causes-a-probe-measured-on-two-sets-not-ready-to-show)), the engine on the stores, the application. It is measured on the team's own questions (E32, E33, E34), and long runs on those have stopped (B-D51). What comes next is an expert's question set, which comes in through [this path](../../EXPERT_PILOT.md) and needs a rented cloud GPU or a hosted open-weight model to run (B-D47); the commands are in [next-runs.md](next-runs.md).

Measurements go into experiment records in [`docs/experiments/`](../../experiments/README.md) (E14 onward). The log links to them and does not copy their numbers.

## Working rules for this stint

1. **Start small (D-44).**
   - Begin with the 15 AK-3 end-of-well report (EOWR) chunks the prototype used, then move to the whole AK-3 EOWR.
   - Daily drilling reports came after the base comparison closed for this stint (E24, E27).
   - Check answers against the prototype's 31 questions and E10's gold facts, then the labelled simulated sets (B-D22). Freeze new questions before running them.
2. **Efficiency is a headline metric.** Every run records:
   - LLM calls;
   - input and output tokens;
   - wall-clock seconds;
   - cost per page and per question;

   alongside quality. A base that is slightly better but several times more expensive per page loses.
3. **Use what exists, then improve it.** Look only at solutions close to our description, take them over and make them better on drilling reports (B-D08). Copied code keeps its credit ([survey](survey.md#licences)).
4. **Keep everything else fixed when comparing.** Every candidate gets the same chunks, questions, model and token budget, so that the comparison measures the pipeline and not the setup.
5. **Log as you go.** A finding, a decision, a design choice or a run goes into [log.md](log.md) the same day. A decision that changes the specification also goes into specification §13.1.
