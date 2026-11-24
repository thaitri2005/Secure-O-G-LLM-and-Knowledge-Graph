# Development and delivery plan

**Version:** 3.3 · **Baseline date:** 23 October 2026 · **Last revised:** 25 November 2026 (second build run with the real model; ready for a server)<br>
**Product target:** a GraphRAG application for drilling reports: ingestion, storage, a coordinator over two graphs and retrieval, chat and administration<br>
**Team:** Tri, Khai, Hung · **Source of truth:** [Project specification](PROJECT_DESIGN.md) · **Direction:** [28 October](requirements/supervisor-meeting-2026-10-28.md) and [9 November](requirements/supervisor-meeting-2026-11-09.md) meetings

This plan schedules the [specification](PROJECT_DESIGN.md). It adds no scope of its own; requirement IDs (FR), gates (G1–G8), decisions (D-xx) and questions (Q1–Q15) refer to the specification.

**Version 3.3 (25 November)** records the first runs with the real model and the reviews, and rewrites the status and the task list (§7) around what now needs people or money. What each track found is in its own record: [Track A progress](experiments/TRACK_A_PROGRESS.md), [Track B log](tracks/B-graphrag/log.md), [Track C log](tracks/C-storage/log.md). Earlier versions are in the Git history.

## Current status

25 November 2026.

**In one paragraph.** The second build is coded in all three tracks, has been run end to end with the real model, and is ready to be put on a server. On a cloud machine without a GPU, the demo package was built from the public PDFs, loaded into the stores with real vectors, and served by the application in containers, with Qwen3-8B answering on the CPU: the recorded baseline came out answer for answer, and the reasoning lane got its first measurement. A design review, a code review and a security review were made and acted on. What is left needs people or money: a server, a GPU for the long measurement, and experts to use it.

| Part | State | More |
|---|---|---|
| Reading the reports (Khai) | The demo package builds with one command, and was rebuilt from nothing on Linux: the end-of-well reports of AK-3, 56-32 and 68-32 and AK-3's daily reports, 302 pages. Newer reading options exist and are off until measured | [Track A log](tracks/A-ingestion/log.md) |
| Stores (Hung) | PostgreSQL with pgvector and Neo4j. One command loads a package and checks each step: 161 events, 207 facts, and now a vector for every chunk, searched inside the database. They restart by themselves and report their health | [platform/README.md](../platform/README.md) |
| Engine (Tri) | A coordinator over four lanes: passages, well facts, events, reasoning about causes. Reads files or the stores. A bench checks a model, runs the measurement suite and compares runs. The baseline is reproduced on a second machine and the reasoning lane is measured; the coordinator's measurement on the pooled questions waits for a GPU | [graphrag/README.md](../graphrag/README.md) |
| Application (Tri, Hung) | A FastAPI backend and a React frontend for non-developers, a question log that exports a test set, one shared password, all as containers. Built for one model slot: questions take turns, failures are logged and told plainly, a monitor and a backup copy are ready to switch on | [backend](../backend/README.md), [frontend](../frontend/README.md), [deploy](../deploy/README.md) |

**What is not done, and what each item waits for**

| Gap | Waits for |
|---|---|
| The coordinator on all 221 pooled questions (E33). On a CPU a question takes minutes, too long for 221 questions twice over | A GPU: the [resource request](reports/RESOURCE_REQUEST_2026-11-24.md) |
| Not on a server that others reach | The same request, or Hung's machine in the meantime |
| No domain expert has used the application or reviewed a question | The supervisor naming one or two people |
| The reasoning lane over-states: it finds the stated cause and also lists nearby events as causes ([E34](experiments/E34-reasoning-probe.md)) | Ours: a smaller unit for "the problem" is built and to be scored on the second probe. Then an expert's reading |
| Value matching in the scorer is looser than described (a numeric gold accepts numbers within 0.5%) | A decision with the first expert-reviewed set: changing it means rescoring every baseline |
| Four benchmark manifests of Track A are referenced by scripts and records and are not in the repository | Khai committing them |

**Results so far** are in the [experiment register](experiments/README.md) and [specification §8.4](PROJECT_DESIGN.md#84-what-the-first-build-runs-today). Every question set is written by the team, and every method is tuned on one well and one report family.

**Direction** (unchanged): a GraphRAG application for drilling reports (D-36, D-40); open-weight models of about 8B or smaller, never commercial APIs (D-37); a coordinator that sends each question to a lane (D-58, D-64); a real application shown to domain experts early (D-60, D-65); rule-based parsing before vision models (D-63); a capstone, not research (D-41, D-44).

## 1. Planning basis

- **Team:** three students. The supervisor expects the end-to-end application in English within the first semester (D-35); hardening and scale follow in the second.
- **Compute:**
  - no GPU of the team's own: the desktop that ran every measurement up to E31 was borrowed and is not planned on (Track B log B-D42, B-D43);
  - **a machine without a GPU runs the baseline model at minutes a question** (4 cores, Track B log B-F71): enough to check the whole system with the real model and for measurements of ten to sixty questions, not for the 221-question pool;
  - **rented from cloud providers, on public data only (D-68):** a GPU by the hour for measurements and experiments, running our own copy of the model; a server for the stores and the application; hosted open-weight models (OpenRouter) for the demo and quick checks. None is paid for yet: the [resource plan](reports/RESOURCE_REQUEST_2026-11-24.md) asks for 5 million VND (about US$190) from the capstone funding for the next three months (Q6, Q7);
  - the school's GPUs are not planned on: the supervisor advised they are slow and awkward (24 November);
  - laptops for code, tests, Docling and the stores.
- **Data:** public only. AK-3 first, then the Utah FORGE reports already used (56-32, 68-32, 78-32). The supervisor's petroleum document, if supplied, is processed on local models only.
- **Questions:** simulated sets stand in for the expert set (Q2, D-49) and are never reported as expert validation. The application's question log is the new route to real questions (D-65).
- **Estimates:** plan week by week. Re-plan at every check-in from what was actually finished.

## 2. Team split

The first build ran as three tracks joined by files (D-48). Those tracks are closed (§3), and K1 to K5 remain the interfaces between ingestion, engine and stores.

From this stint the split follows the lines the supervisor asked for (D-46, D-65). The roles are settled for this stint (Q14): Hung and Khai agreed on 24 November, and Hung asked Tri to do part of the backend for now ([backend design](tracks/C-storage/backend-design.md); Track B log B-D40).

| Role | Owner | Owns | Interface it publishes |
|---|---|---|---|
| **Data** | Khai | PDFs to K1 packages; table and form quality; the QA sidecar; new reports | K1 releases |
| **Backend** | Hung, with Tri for now | Shared hosting of the stores; the runner from a K1 package to loaded stores and graphs; the FastAPI service; the question log | The OpenAPI file; the stores |
| **Engine** | Tri | Lanes, coordinator, answer checks, the reasoning probe; measurements | The `graphrag` library; K4 records |
| **Frontend** | Tri | The React application | — |

Engine and frontend on one person is the weak point of this split. If it slips, the frontend's first version shrinks to the chat page and the source viewer.

The split is redone every one to two weeks (D-48). Everyone joins integration, demos and documentation.

## 3. Milestones

Weeks are counted from 2 November 2026. Windows are indicative; each check-in revises them.

| Milestone | Window | Exit demo | State |
|---|---|---|---|
| **M0: Plan, access, workflow demo** | Week 1 | Tracks assigned, contracts at version 0, workflow shown | Done, except the OpenRouter account (Q6) and how rented compute is paid for (Q7) |
| **M1: First build in three tracks** | Weeks 1–4 | One-document slice from pages to cited answers | **Closed 24 November**; see below |
| **M2: Second build — one connected application** | Weeks 4–6 (24 November to 12 December) | A person outside the team opens the application, asks about AK-3, and sees the answer, the lane used, the cited page and the evidence. Everything is read from the shared stores, loaded by one command | **Current** |
| **M3: Quality and control** | Weeks 6–9 | Wells linked to registry IDs; glossary in use; scores and flagged items; 5–10 documents from more than one report family; the expert or logged questions run (G3–G6) | Outline |
| **M4: Full application** | Weeks 7–11 | A non-developer uploads a report, watches the run, corrects three flagged items, edits a glossary entry, asks a question and opens the cited page | Outline |
| **M5: Scale run on local models** | Weeks 10–13 | The corpus processed in checkpointed runs on a rented GPU; evaluation on held-out questions; cost and throughput report (G8) | Outline |
| **M6: Access control and hardening** | Second semester | Login and roles; private-endpoint guard tested (G7); backup and restore; joint evaluation on the supervisor's document if supplied | Outline |

![Milestone dependencies](diagrams/07-milestone-dependencies.svg)

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart LR
    M0["M0 (done)<br/>Plan, access,<br/>workflow demo"]:::done --> M1["M1 (closed)<br/>First build:<br/>three tracks"]:::done
    M1 --> M2["M2 (now)<br/>Second build:<br/>one connected<br/>application"]:::now
    M2 --> M3["M3<br/>Quality and<br/>control"]
    M2 --> M4["M4<br/>Full<br/>application"]
    M3 --> M4
    M3 --> M5["M5<br/>Scale run on<br/>local models"]
    M4 --> M5
    M5 --> M6["M6<br/>Access control<br/>and hardening"]
    classDef done fill:#e4f3ea,stroke:#3b7d57,color:#1b2a3a
    classDef now fill:#fdf0d0,stroke:#a67512,color:#1b2a3a,stroke-width:2px
```

</details>

**Figure 7 — Milestone dependencies.** The critical path is the K1 release for the demo set → the stores loaded by one command → the engine reading the stores → the API → the frontend → domain experts using it.

### M1: how the first build closed

| Track | Exit asked | Met | Not met; where it goes |
|---|---|---|---|
| A. Ingestion and tables (Khai) | A parser choice with table scores; K1 version 1 for both documents | K1 version 1 adopted (D-57). Docling stays the general parser, with rules for known table formats. Operations Summary tables rebuilt: 81 of 81 on seen data, and 27 of 27 found on a held-out round | The document VLM comparison was not run; deferred by D-63. Tables over several pages: options exist, off by default and not yet measured on end-of-well reports. Generalization beyond one report family. → M2 task D2, M3 |
| B. GraphRAG engine (Tri) | A base, an LLM, an embedding model and a vector store chosen; K4; cost per page | Qwen3-8B, Qwen3-Embedding-0.6B and pgvector chosen. No third-party base adopted; our own two graphs instead (D-53, D-55). K4 version 0.1. Cost reported on every run | Answers on K1 version 1 and on the stores. → M2 tasks E1, E2 |
| C. Storage and the run (Hung) | Schemas with validators; four stores loaded; page-rebuild check; one-command runner; viewer | K1 tables with constraints; loader and page rebuild; vectors; the event graph in Neo4j | The runner and the full pass through it; the viewer (Track B's local UI stood in); MinIO in use; the fact graph in Neo4j; shared hosting. → M2 tasks B1 to B3 |

### M2: second build, one connected application

The design is [specification §4.6](PROJECT_DESIGN.md#46-second-build-one-connected-application), [§7.5](PROJECT_DESIGN.md#75-http-interface-design) and [§8.1](PROJECT_DESIGN.md#81-the-coordinator-and-its-lanes). The task list is §7 below. Three checkpoints:

| When | Checkpoint | State on 25 November |
|---|---|---|
| End of week 4 (28 November) | Roles agreed. Supervisor messaged. Stores reachable by all three, with the AK-3 release loaded. The OpenAPI file agreed. The lane interface written, with the lanes behind it | All built; the stores loaded with the three-report package and its vectors on a cloud machine. Open: the message to the supervisor, a host all three reach |
| End of week 5 (5 December) | The engine answers from the stores, with the baseline scores reproduced. The coordinator measured on the pooled questions. The API returns real answers. The frontend runs against it | Done, except the coordinator's measurement on the pooled questions, which waits for a GPU |
| End of week 6 (12 December) | The exit demo above, shown to the supervisor: one sample walked from PDF to answer inside the application. The reasoning probe's record written. The application handed to whoever the supervisor names among the domain experts | The record is written ([E34](experiments/E34-reasoning-probe.md)). The demo and the hand-over wait for a server and for names |

**Order matters more than dates.** The first two things unblock everyone else: shared stores (B1) and the K1 release for the demo set (D1). The frontend does not wait for them: it starts on recorded answers as fixtures.

### M3: quality and control

1. **Identity and glossary.** Link report mentions to the registry, and AK-3 to its project-scoped entry. Link daily reports to their well through `Document` nodes. Use the glossary in the question frame.
2. **Generalization.** Reports from more than one family: the 58-32 daily reports, a different author's modern end-of-well report (Track B log B-F54), tables over several pages, and the QA thresholds calibrated on more than one family.
3. **Scores and flagged items.** Compute scores, set the threshold from a labelled sample, and list flagged items for people (D-43, D-63).
4. **Questions.** Run the expert set if it has arrived; otherwise the questions domain experts typed into the application, with gold answers written from the reports.
5. **Lanes.** Split, merge or add lanes from what the question log shows (Q13). Decide whether the reasoning lane becomes a loop (D-64).

### M4: full application

- **End user:** well page (facts, documents, timeline of days); graph and source browsing.
- **Admin:** document upload and run status; ontology versions with validation and diff; glossary editor; flagged items with accept, correct and reject; duplicate wells; generation activation; document retirement.
- **Governance:** versions and audit of every correction and activation.
- Keep the UI plain: tables and lists before graph visualizations.

### M5: scale run on local models

Serve the chosen model ourselves (vLLM or llama.cpp) on a rented cloud GPU (D-68). Process the corpus in checkpointed runs that stop and resume across slots, then evaluate on held-out questions. Estimate first from the measured cost per page; prepare data, containers and models before the slot starts.

### M6: second semester

- Login, roles and server-side checks.
- The private-endpoint guard test.
- Backup and restore of PostgreSQL, the file store and Neo4j.
- The joint evaluation with the supervisor's document if supplied, on local models only.
- Improvements chosen from the evaluation.

## 4. Compute and cost control

| Item | Approach | Control |
|---|---|---|
| A GPU of our own | None (Track B log B-D43). Runs up to E31 were made on a borrowed desktop | Their recorded scores stand; nothing new is planned on that machine |
| Hosted open models (OpenRouter) | The demo's model and quick checks, public data only (D-68) | A cap on the account; cost per run reported (FR-30); never private data (spec §10.1); a hosted score is compared only with a baseline rerun on the same endpoint |
| A cloud GPU rented by the hour | Every measurement, experiment and large run, with our own copy of the model (D-68) | Switched off after each session; hours and cost recorded with each run; model files kept on a rented disk; one request at a time; public data only |
| School GPU slots | Not planned on (D-68) | — |
| Shared host for the stores | A rented cloud server, from student credits or the requested budget; interim: Hung's machine over a private network, if he agrees (Track C log C-D06, C-D07) | Public data only; credentials outside the repository; one shared password in front of the application until login exists |

Every run reports calls, tokens, seconds and cost per page and per question next to quality. The coordinator adds one model call to lookups; that cost is measured before it is adopted (D-64).

**Scope cuts if time runs short**, in this order:

1. graph visualization;
2. the well page;
3. the reasoning lane beyond its probe;
4. the ontology assistant and extra document types;
5. corpus size.

Keep:

- citations and the source page;
- the ID scheme;
- the coordinator with its lanes;
- the question log;
- the private-data boundary.

## 5. Risks

| ID | Risk | Watch for | Mitigation | Owner |
|---|---|---|---|---|
| R-01 | A ~7B model states plausible but wrong facts | Wrong values in answers; unsupported claims in the reasoning probe | Values and citations checked in code; computed results inserted by code; facts validated before use; causes labelled stated or possible | Engine |
| R-02 | Table parsing errors propagate | Wrong cells, missing headers, lost marks | Rules for known formats with a fallback and a reason; the QA sidecar; measure on other report families | Data |
| R-03 | Methods tuned on one well do not transfer | A second report family fails | Add one new family at a time in M3; report seen and unseen data separately | Data, Engine |
| R-04 | The coordinator sends questions to the wrong lane, or trusts a field the model got wrong | Pooled score below the hand-routed scores; the faults of [E34](experiments/E34-reasoning-probe.md) | Wells and dates read by code; fixed fallback; measured before adoption; a lane can be forced from the UI | Engine |
| R-05 | No GPU for the long measurement and no server others reach: no budget yet | No approval of the resource plan | Ask now (Q6, Q7). A machine without a GPU already covers the short measurements (Track B log B-F71); a hosted model for a few dollars covers the pooled one | All |
| R-06 | Hosted endpoint used on non-public data | A private file in a run | The backend's check at start: a hosted model only gets packages named as public, and any address outside the private network counts as hosted (specification §10.1) | Engine |
| R-07 | No public daily-report collection beyond AK-3 | Reasoning and event lanes stay on one well | The 58-32 daily reports; keep looking (Q5); say so in every result | Data |
| R-08 | Real questions never arrive | No expert set, and nobody uses the application | Simulated sets, labelled; put the application in front of experts early; ask at each check-in | All |
| R-09 | Scope too large for three people; engine and frontend on one person | A checkpoint missed by a week | Cut in the order of §4; shrink the frontend to chat and source viewer | All |
| R-10 | Direction drifts without contact | **Already true: no recorded contact since 9 November** | Message the supervisor this week (§7, task 2); short updates every few days (D-46) | All |
| R-11 | Wrong entity merges corrupt answers | Two wells joined | Identifier and scoped-name matching only; merges always by a person | Backend |
| R-12 | The three parts drift while being connected | A K1 or API change breaks another part | K1 changes by version only; the OpenAPI file agreed first; the runner checks each step | All |
| R-13 | Data passed by hand between machines | A zip in the chat | Shared stores and a file store for K1 releases (B1) | Backend |
| R-14 | The demo is down, or loses the question log, and nobody notices | An expert says so first | The monitor and the backup copy off the server, switched on before the first expert gets the link (task S3); a restore check | Backend |
| R-15 | A score moves because the scorer or the facts changed, not the system | A number that differs from its record | Each record names its run files; scorer and fact-check changes are logged with what they did to recorded rows (B-F68, B-F69) | Engine |

## 6. Working cadence (D-46)

- **Weekly check-in with the supervisor, about 30 minutes:** what was done, what is blocked, next week's plan. Bring a demo whenever something runs.
- **Group chat updates every few days:** a short message or a screenshot. Message the supervisor when there is a result worth showing; do not wait for a meeting.
- **Reports are short:** two or three slides of architecture, one sample walked through the pipeline, weak points stated, then what the team needs (9 November meeting).
- **Review.** Each change is reviewed by another student before merging to `main`.
- **Record decisions.** A supervisor decision becomes a decision in spec §13.1 in the same week. Superseded text is removed, not kept beside the new text.

### Definition of done

- Demonstrated on real data (one document at least) or a fixture.
- Another student reviewed it.
- IDs and citations resolve.
- Calls and cost reported where models are used.
- Limitations written down.

## 7. What to do now

Tasks for M2. Everything that code, a laptop or a machine without a GPU can do is done. **What is left starts with a message to someone outside the team, or with money.**

### Now, in order: each needs a person

| # | Who | Do | Unblocks |
|---|---|---|---|
| 1 | Tri | Send the [resource request](reports/RESOURCE_REQUEST_2026-11-24.md) to anh Trường | A server and a GPU |
| 2 | Tri | Send the [stint report](reports/stints/STINT_REPORT_2026-11-27.md) to anh Tuấn, with three questions: who can try the application, what it is for, and whether a private document will come | Real questions; the purpose of use |
| 3 | Hung | Say whether his machine hosts the stores and the application until there is a server; create the group chat's incoming webhook for the monitor | A place others reach |
| 4 | Khai | Commit the four benchmark manifests the Track A scripts read; review the demo package and the Track A log; measure the reading options (D2) | Track A's records reproducible |
| 5 | All | Read the three reviews' changes in each track's log and object if something is wrong | — |

### Once there is a server (half a day, [runbook](../deploy/README.md))

| # | Do |
|---|---|
| S1 | Follow the runbook sections 1 to 9: stores, the package with its vectors, the application behind the password, the smoke test from outside |
| S2 | Set `BACKEND_PUBLIC_RELEASES=demo-v2` if the model is a hosted one; set the model time limits for the model in use |
| S3 | Switch on the backup with its copy off the server, run the restore check once, and start the monitor from another machine (runbook sections 11 and 12) |
| S4 | Hand the address and the password to the people the supervisor names |

### Once there is a GPU (one session of a few hours, [commands](tracks/B-graphrag/next-runs.md))

| # | Do |
|---|---|
| G1 | `python -m graphrag.bench run qwen3-8b.local --suite full --k1 data/interim/k1/demo-v2`: the coordinator on the 221 pooled questions against the hand-routed scores (E33), and the answers on the package (E32) |
| G2 | Decide whether the coordinator is adopted (D-64): only if it matches the hand-routed scores |

### Data (Khai)

| # | Task | State | Left |
|---|---|---|---|
| D1 | A package for the demo: three end-of-well reports, AK-3's four daily-report attachments and its non-productive-time report, with the old-to-new ID map | Built (`demo-v2`), and rebuilt from the public PDFs on Linux with the same pages and one more chunk | Khai's review |
| D2 | Decide which reading options are on by default, by measurement on this package | Not done | Khai |
| D3 | Add the 56-32 and 68-32 end-of-well reports | Done, in `demo-v2` | Khai's review |
| D4 | Merged-cell text repeated in table Markdown | The fix exists as an option, with a test | Switch it on, with D2 |
| D5 | A dated Track A log | A draft exists | Khai corrects it |
| D6 | The benchmark manifests under `configs/benchmarks/` that four scripts and five records point to | Not in the repository | Khai commits them |

### Backend and stores (Hung)

| # | Task | State | Left |
|---|---|---|---|
| B1 | A host for the stores that all three reach | Scripts and a runbook ready; run on a cloud machine | A host: Hung's machine or a rented server |
| B2 | One command from a package to loaded stores | Done, with the embedding model: 1,432 vectors, the database search equal to the search in memory | — |
| B3 | Both graph regions in Neo4j | Done: 207 facts, 202 on the package's chunk IDs | 5 facts on old IDs, with no chunk to show |
| B4 | The API contract | Done | — |
| B5 | The backend service | Done; answers from the stores with the real model | — |
| B6 | The question log | Done, in PostgreSQL; failed questions are logged too | — |
| B7 | Page images for the source viewer | Done: 302 pages rendered and served | Render them on the host |
| B8 | The whole application as containers behind one password | Done; built and checked from outside on a cloud machine | A server and a domain |
| B9 | Know when it is down; keep the question log | A monitor script, a backup copy off the server and a restore check exist | Switch them on (S3) |

### Engine (Tri)

| # | Task | State | Left |
|---|---|---|---|
| E1 | Answers on the new package (experiment E32) | The package, the stores and the application answer with the real model | The scores on a GPU (G1) |
| E2 | The engine reads the stores | Done, on real vectors | — |
| E3 | Lanes behind one interface; model roles in a settings file | Done | — |
| E4 | The fact graph as nodes and relationships | Done; rebuilt after nine wrong facts were found (207 facts) | One known wrong fact (AK-3, days from spud to release) |
| E5 | The coordinator (experiment E33) | Built | The pooled run on a GPU (G1), then the decision (G2) |
| E6 | Totals reported by code, not retyped by the model | Built | Measured with E33 |
| E7 | The reasoning lane (experiment E34) | Measured on two probes: it finds the stated cause and over-states; rules in code remove most of it on the first probe | Score the last rule on the second probe; an expert's reading |
| E8 | A bench for models | Done; the baseline reproduced with it on a second machine | — |

### Frontend (Tri)

| # | Task | State | Left |
|---|---|---|---|
| F1 | The question page, a page per well, the questions people asked | Done; checked against the stores in a browser | First use by someone outside the team |
| F2 | The source viewer: the page beside the cited passage | Done, with the printed page | — |
| F3 | The evidence panel: timeline, report text, facts, causes | Done; long lists fold and the answer stays in view | — |
| F4 | Right or wrong, with a comment | Done | — |
| F5 | Waiting, busy and failure told in plain words; usable on a phone and by keyboard | Done; an accessibility scan is clean | A test with a screen reader |

### After M2

The M3 to M6 lists in §3.

The main [README](../README.md) stays the setup entry point.

## 8. Decisions to close

| Decision | Needed by | Why |
|---|---|---|
| Where the demo runs and which model serves it (Q15) | 5 December | Domain experts must reach it without the team's laptops |
| Purpose of use and question types (Q13) | M3 | Decides how lanes are split or merged (D-58) |
| Expert question set, or which experts try the application (Q2) | M3 | Evaluation; simulated sets stand in for development only |
| Whether the coordinator is adopted (D-64) | After record E33 | It adds one model call to lookups |
| Whether the reasoning lane's two-part answer is the right shape, and whether "possible factors" are wanted | When an expert reads ten answers | Decided for now: it continues as a probe ([E34](experiments/E34-reasoning-probe.md), D-66) |
| Whether the scorer's value matching is tightened | With the first expert-reviewed set | It would change every recorded baseline (Track B log B-F70) |
| OpenRouter account owner and cap (Q6); how rented compute is paid for (Q7) | Now | Open since M0; the resource request asks |
| Public daily-report sources beyond AK-3 (Q5) | M3 | Daily reports are half of the document scope |
