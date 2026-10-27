# Development and delivery plan

**Version:** 2.2 · **Baseline date:** 23 October 2026 · **Last revised:** 27 October 2026<br>
**Product target:** a maintained internal service for one small team<br>
**Team:** three students · **Source of truth:** [Project specification](PROJECT_DESIGN.md) · **Data:** [Data sources](DATA_SOURCES.md)

This plan schedules the [specification](PROJECT_DESIGN.md): deliverable work, dependencies, ownership, estimates, and risks. It adds no scope of its own; requirement IDs (SR, FR), gates (G1–G9), decisions (D-xx) and open questions (Q1–Q9) refer to the specification. When the specification changes, revise this plan in the same change. The implementation currently stops at ingestion and a prototype. Future milestone names do not imply that their features are already present.

## Current status

**Focus.** Build a domain-agnostic platform and deliver one **oil-well** application profile, initially in **English** (specification D-26/D-27). Develop on [BSEE well data](DATA_SOURCES.md#1-bsee-data-center--wells-information) and English end-of-well reports, with [AK-3](DATA_SOURCES.md#2-akutan-ak-3-end-of-well-report-the-document-exemplar) as an existing development proxy. Oil terminology belongs in profile/adapters, while source/evidence/review/publication contracts remain reusable. Additional domains, interpretation/expert-note workflows and multilingual delivery are later scope.

**Implemented** (code, tests and a verification record exist):

| Item | Milestone | Guide | Evidence |
|---|---|---|---|
| Domain-neutral document ingestion: supported formats, per-page OCR, Vietnamese OCR, quality flags, content-addressed catalog, resumable parallel processing and staged export; atomic replacement remains open | M1 (FR-01, FR-02, FR-13; v2 chunk envelope) | [Document ingestion](components/corpus-ingestion.md) | [E5](experiments/E5-ocr-engine-benchmark.md), [E7](experiments/E7-corpus-pipeline-smoke.md), [E8](experiments/E8-ak3-appendices-corpus-run.md), [E9](experiments/E9-repository-review.md) |
| Mapping-driven structured-data import with row provenance, checks and graph rules; BSEE as a mapping | M1 (FR-15); M3 groundwork (FR-16) | [Structured-data import](components/dataset-import.md) | [E6](experiments/E6-generic-import-bsee.md) |
| PDF ingestion with page/region/offset provenance, evaluation and publication | Pre-M1 baseline | [PDF ingestion](components/pdf-ingestion.md) | [E1](experiments/E1-pdf-ingestion-configuration.md), [E3](experiments/E3-reproduction-run-2026-10-25.md) |
| Local PDF registration, opt-in Vietnamese–English OCR, source-aware cache checks, scanned-page coverage checks | M1 (partial) | [OCR ingestion](components/ocr-ingestion.md) | [E2](experiments/E2-vietnamese-ocr-smoke.md) |
| BSEE well-data adapter: verified snapshot, typed records with row provenance, well grouping, schema validation | M1 (partial; FR-15) | [BSEE ingestion](components/bsee-ingestion.md) | [E3](experiments/E3-reproduction-run-2026-10-25.md) |
| BSEE linked graph within the source (wellbores, wells, operators, leases, blocks, fields), every edge citing its row | M3 groundwork (seed of the entity registry, FR-16) | [BSEE ingestion](components/bsee-ingestion.md#linked-graph) | [E3](experiments/E3-reproduction-run-2026-10-25.md) |
| Architecture prototype (test build): AK-3 extraction, validation, review queue, Neo4j generations, cited QA | Evidence for the M2/M3/M5 design, not a completed milestone | [Prototype](../prototype/README.md) | [E4](experiments/E4-ak3-architecture-prototype.md) |

The [experiment register](experiments/README.md) holds repository measurements. E4 demonstrates laptop integration and weak prose recall on a development slice; it does not establish architecture reliability under failure or independent QA quality. The [27 October review](REPOSITORY_REVIEW_2026-10-27.md) reproduced publication, dataset and date-validation defects ([E9](experiments/E9-repository-review.md)); they remain unfixed. All 128 main tests and four prototype ontology tests passed. The unified [progress report](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) brings together ingestion, WebNLG/2Wiki/EOR method evaluation, graph construction and prototype QA. The next slice integrates these workstreams through shared evidence/claim contracts.

**Next milestone.** A real reviewer accepts a versioned oil-well claim; three English question intents return cited knowledge; interrupted replacement preserves accepted data; withdrawal immediately blocks serving. Freeze the English oil-well evaluation split before prompt tuning. Extract the profile boundary from the existing well-specific prototype and check it with a small synthetic configuration fixture.

**Not yet started for the first delivery:** generic registry/profile contracts (FR-16), reusable extraction and query dispatch, language-tagged/scoped English aliases (FR-18). **Still open in M1:** representative English scan/table quality checks, web upload on the catalog, access skeleton and dataset snapshot comparison. Existing Vietnamese OCR and AK-3 corpus runs remain completed evidence; FR-17 and multilingual rollout move to later scope.

## 1. Planning basis

The team confirmed three students, an internal production target, limited school/cloud resources, and possible access to an RTX 4080 SUPER-class GPU or an A100. No deadline, weekly availability, spending ceiling, or permanently allocated host has been confirmed.

Use **20 working weeks as an illustrative baseline**, assuming each student contributes an average of 12 hours/week: `3 × 12 × 20 = 720 person-hours`. Allocate approximately **576 hours to planned delivery and 144 hours (20%) to contingency**, integration surprises, and rework. These are rough planning estimates with at least ±30% uncertainty until the first model and deployment spikes are complete. They are not a fixed-price or completion-date commitment.

At 8 hours/student/week, the same 720-hour capacity would take about 30 working weeks; at 15 hours it would take about 16. Exams, holidays, hardware queues, and institutional approvals can extend elapsed calendar time without adding engineering hours. Re-estimate after M1 and M2 using actual delivery speed.

The baseline delivers one English oil-well profile on a reusable core, one shared document-access boundary, a small question catalogue, a simple review interface and single-host deployment. Start integration on 5–10 representative English reports, implement three intents first and agree 5–8 for the initial workload. These are workload limits; held-out acceptance sizes remain unchanged. Defer second-domain delivery, subsurface interpretation, expert-note capture, Vietnamese/Russian rollout, fine-tuning, multi-GPU inference, high availability, multi-tenancy and an elaborate graph editor.

The 720-hour capacity model below remains a historical planning illustration. Re-estimate remaining work for one English oil-well profile, explicit generic-core interfaces, reliability fixes, annotation/review and deployment using actual weekly availability. Removed second-domain/expert-note/multilingual work reduces breadth; it does not establish a new delivery date or automatic cost saving. Measure review effort and preserve contingency.

## 2. Team responsibilities

Assign actual names at kickoff. A role is an area of responsibility, not an exclusive silo; all three students participate in integration, tests, documentation, and pilot support.

| Role | Primary responsibility | Secondary / review responsibility |
|---|---|---|
| Student A — Data and extraction | Ingestion adapters, evidence contracts, ontology, extraction, model benchmark | Review graph data model and numerical/citation correctness |
| Student B — Backend and graph | PostgreSQL workflow, jobs, graph projection, publication, QA query templates | Review deployment/recovery and API authorization |
| Student C — Application and operations | UI, evidence viewer, identity integration, deployment, monitoring, runbooks | Review user acceptance and operational test evidence |
| Product/domain owner — to name | Scope priorities, ontology meaning, question catalogue, pilot acceptance | Provide reviewer availability and resolve ambiguous domain labels |
| School IT / host operator — to name | Host allocation, access, identity/TLS integration, backups, post-project maintenance | Approve the operating environment and private-data boundary |

Student A coordinates the model/extraction benchmark, B coordinates technical integration, and C coordinates release readiness. Rotate meeting facilitation and peer review so project knowledge is shared. No milestone closes on its author's self-assessment alone.

### Responsibility matrix

`A` = accountable for closure; `R` = does the work; `C` = consulted; `I` = informed. One accountable owner per row.

| Deliverable | Student A | Student B | Student C | Product/domain owner | IT/operator |
|---|---|---|---|---|---|
| Scope, supported questions, acceptance priorities | C | C | R | A | C |
| Source/evidence contracts and extraction | A/R | C | C | C | I |
| Graph, jobs, API, query templates | C | A/R | R | C | C |
| UI and evidence inspection | C | R | A/R | C | I |
| Ground-truth labels and domain adjudication | R | C | R | A | I |
| Staging deployment and restore demonstration | C | R | A/R | I | C |
| Production hosting and ongoing operation | I | C | R | C | A |
| Product release acceptance | C | R | R | A | C |

If no domain owner or operating owner is available, work can continue on a public-data prototype, but internal production acceptance cannot be represented as complete.

## 3. Milestones and work packages

Effort is combined team effort, including peer review, milestone tests, and relevant documentation. Calendar windows overlap only where different students can work against agreed interfaces. The exit criteria reference [design gates G1–G9](PROJECT_DESIGN.md#122-proposed-release-gates).

| Milestone | Indicative window | Effort | Lead | Dependencies | Reviewable deliverable and exit condition |
|---|---|---:|---|---|---|
| M0 — Scope and host feasibility | Week 1 | 12 h | C, with product owner | None | Supervisor meeting on the open questions Q1–Q9; confirm service audience, one-workspace policy, host access, operator path, workload, question shortlist, and spending control; record decisions |
| M1 — Reproducible ingestion boundary | Weeks 1–2 | 44 h | A | M0 | Clean setup, independent bundle verification, source-neutral v2 envelope/local upload adapter, input limits, baseline access skeleton, immutable run manifest; G1/G2 cases defined |
| M2 — Ontology and local extraction slice | Weeks 3–5 | 80 h | A | M1 | Generic registry/profile contracts (FR-16/18), one `oil_wells` ontology; English PDF → typed candidates → evidence; externalize prototype rules; synthetic profile fixture; frozen English evaluation split; initial G3 |
| M3 — Accepted knowledge and graph publication | Weeks 6–8 | 72 h | B | M2 contracts | Claims/reviews in PostgreSQL; profile-driven registry seeded from BSEE; Neo4j exact-set projection, activation, retry/rollback; G1/G4 and crash cases |
| M4 — Team application and review workflow | Weeks 6–11 | 104 h | C | M1 API/auth; M3 before closure | Login/roles, uploads/jobs, claim/evidence review, conflicting values and identity merges, publication/retirement UI; unauthorized direct requests denied |
| M5 — Bounded question answering | Weeks 12–14 | 84 h | B | M3/M4; frozen English question catalogue | Profile-selected oil-well intents and trusted parameterized queries, deterministic answers, citations and abstention; English passage-retrieval baseline; G5/G6 |
| M6 — Production hardening | Weeks 15–17 | 88 h | C | M3–M5 | Pinned deployment, actual-host load/VRAM tests, offline test, fault tests, backup/restore, retirement propagation, runbooks; G7/G8 evidence |
| M7 — Pilot, corrections, and handover | Weeks 18–20 | 92 h | C, with product owner | M6 technical gates | At least 3 intended users, task/time comparison, defects resolved, release checklist, operator training and acceptance; G9 and all release gates signed off |
| **Total planned delivery** | **20-week illustration** | **576 h** | | | **Plus 144 h reserved capacity; total 720 h** |

The milestone table retains the earlier 576-hour allocation for comparison. Re-estimate the narrowed English oil-well scope and remaining core/profile work, reliability fixes, annotation and integration before committing dates. Authentication/direct-route checks begin in M1/M4, publication crash cases in M3, and withdrawal/restore in the first complete slice; M6 repeats them on the agreed host.

![Milestone dependencies](diagrams/07-milestone-dependencies.svg)

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart TB
    M0["M0<br/>Scope and host"] --> M1["M1<br/>Ingestion contracts"]
    M1 --> M2["M2<br/>Ontology and extraction"]
    M2 --> M3["M3<br/>Reviewed graph publication"]
    M1 --> M4["M4<br/>Application and review"]
    M3 --> M4
    M3 --> M5["M5<br/>Bounded QA"]
    M4 --> M5
    M5 --> M6["M6<br/>Hardening and recovery"]
    M6 --> M7["M7<br/>Pilot and handover"]
```

</details>

**Figure 7 — Milestone dependencies.** UI foundations can begin before graph publication is complete, using agreed fixtures/contracts. The working review journey depends on M3. The likely critical path is ingestion contracts → extraction quality → reviewed graph → cited QA → recovery/security validation → pilot acceptance.

### M0: decisions before the team commits a calendar

- Inventory the actual GPU and available allocation. An A100 partition may expose less memory than the physical card; record what the process can actually use.
- Confirm that the research machine may host a persistent service, whether other workloads compete for resources, and who can administer it after the project.
- Confirm the institutional login, network/TLS route, backup destination, data classification, and expected support hours.
- Agree 5–8 initial question intents, implement three first, and identify a domain reviewer. Decide whether all team readers may view all published documents.
- Agree weekly availability and a currency-denominated spending ceiling. Record the owner of any cloud account and its shutdown/budget controls.
- Take specification §13.2 to supervisors: approved English oil-well sources, well-property/question catalogue, reviewers, host/data boundary and expected end state. Record answers in §13.1; the team’s one-profile, English-first direction is already recorded as D-26/D-27.

**Output:** a one-page decision record, confirmed backlog priorities, and a revised milestone calendar if needed. Do not buy hardware or reserve paid instances merely because the estimates mention them.

### M1: protect the existing ingestion work

Retain the current GDR v1 bundle and its hashes as a regression fixture. Build adapters around its contract. Move GDR-specific source fields into an adapter/metadata namespace for the v2 application envelope, define the local-upload permission record, and validate unknown schema versions explicitly. Decide per-document ID limits before large-file support.

Add source hash and parser/model/package/configuration fingerprints to production cache eligibility. Stage each run in an immutable output location and activate a bundle only after full validation. Define scan/partial-document behavior: the UI must show gaps, and claims from unsupported pages cannot be presented as extracted knowledge. Begin identity integration and deny-by-default API access here; auth is not a final-week addition.

The structured-data path belongs to M1 as well. The BSEE adapter (done) verifies snapshots and emits typed records with row provenance. Still to do: a snapshot comparison (added, changed, and removed boreholes) to support the snapshot-level review proposed in [design §5.7](PROJECT_DESIGN.md#57-structured-well-data-and-the-entity-registry).

**Exit demo:** process one supported public PDF (AK-3), locate a chunk in the exact PDF version, reject an unsupported file, and prove that reprocessing cannot silently replace the accepted bundle. Import a BSEE snapshot, show a borehole with its row citation, and show that a tampered snapshot is rejected.

### M2: smallest complete extraction example

Work on the two [data source](DATA_SOURCES.md) tracks within one oil-well application. Define generic source/evidence/claim/entity contracts and a versioned `oil_wells` profile: Well/Wellbore types, identifier schemes, scoped English aliases, properties, units, MD/TVD and planned/actual context. Start from the prototype’s 14 properties and move hardcoded assumptions into profile assets or registered rules. Seed identity using the BSEE adapter. Freeze English development/test documents and questions; keep existing AK-3 results as the baseline. A small synthetic non-well profile fixture verifies configuration loading, validation and dispatch without adding a second delivered domain.

Before building a broad pipeline, use one short English well-report section, one relation type, and one quantity type. Produce typed JSON with original value/unit, normalized value only when a rule exists, planned/actual qualifiers and an exact evidence span. Include ambiguous English aliases, conflicting reported values, MD/TVD distinctions and a misleading embedded instruction. Compare model output with deterministic checks and a manual reference.

Benchmark two or three eligible small instruction models, starting around 7–8B parameters with 4-bit weights. Record checkpoint/license, weight/tokenizer hashes, runtime version, prompt/schema, context budget, GPU allocation, peak VRAM/RAM, latency, schema-valid output rate, factual precision/recall, and numerical/citation errors. A public-data cloud run may screen candidates, but final acceptance uses the agreed school-host profile.

Create development/test documents and label at least the initial portion of the 200-claim acceptance set. Add a second annotation pass for a subset and a disagreement log. Selection weighs factual correctness, evidence fidelity, and review effort before speed. Do not choose a larger model solely because an A100 happens to be available.

**Exit demo:** a local command takes versioned chunks and ontology and writes reviewable candidates with evidence; invalid output is bounded and visible. No automatic graph publication yet.

Freeze the held-out document split and matching rubric before the next E4 prompt or model comparison. Use E4's 15 chunks only for development. Add full claim/answer context checks and report missed-fact coverage separately from correct abstention. Measure a real reviewer's time and corrections before sizing a large extraction run.

### M3: durable knowledge and reproducible graph

Implement relational migrations for document/run metadata, the generic entity registry, profile versions, candidate/claim revisions, review decisions, jobs, outbox and graph-generation pointers. Load BSEE wells and wellbores through the oil-well adapter/profile. Test duplicate names, scoped English aliases, external identifiers, merges and reversal. Build claim/evidence nodes using canonical registry IDs and a generation marker. Claim-to-claim interpretation links remain later scope.

Inject failures before and after outbox processing and generation activation. A job retry must not duplicate effects. A missing projection marker must fail closed. Restore a graph from accepted records without rerunning the language model. Demonstrate that conflicting reported well values remain independently inspectable.

**Exit demo:** a reviewed oil-well claim becomes queryable with its source; one registry entity links dataset and report claims; a failed replacement preserves the old graph; rollback selects a validated generation. Prefer an approved English report for a BSEE well; otherwise label a synthetic linking fixture explicitly.

### M4: a usable review application

Implement document list/upload and coverage, job detail, claim/evidence review, entity identity/conflicting values, publication summary and minimal administration. Keep labels and question examples in English. Interpretation links and expert-note entry remain later extensions. Prefer a clear fact table and relationship list before force-directed visualization.

The review view must show exact text, physical page, highlighted region where reliable, table headers for numeric cells, ontology rule, and validation issues. Never force a reviewer to approve a claim without access to its source. Correcting a claim creates a revision and requires a reason. Test stale edits from two reviewers and retired-source behavior.

**Exit demo:** someone outside the developer who built the screen uploads a report, understands warnings, reviews candidates, publishes accepted facts, and withdraws the source. Reader-role attempts to perform those changes fail at the API.

### M5: reliable answers within a defined scope

Implement the supported-intent schema and versioned query catalogue. Start with direct structured search and deterministic answer formatting, then add natural-language intent classification. Optional generated wording comes last and retains a deterministic fallback.

Create at least 60 held-out English oil-well questions covering supported intents, missing information, ambiguous identity, conflicting values, planned/actual and MD/TVD distinctions, cross-source links, withdrawn evidence and adversarial instructions. Measure results before/after optional model wording, and compare against direct PDF search and a simple English passage-retrieval baseline on the same questions.

**Exit demo:** a supported question produces a correct answer, an exact citation, and the served knowledge revision. Ambiguous questions request clarification. Unsupported and unavailable cases are distinguishable.

### M6: operate the system on the actual host

Package the application, worker, stores, and model runtime with pinned versions. Benchmark the 16 GB-class baseline first unless a different device is the only confirmed resource. Record GPU sharing and cold/warm behavior. Verify Linux ingestion output against the Windows reference instead of assuming byte equality.

Exercise restart during each stage, database/model outages, resource limits, full-disk prevention, rejected uploads, unauthorized routes, prompt/query injection, immediate withdrawal, and backup restore. Run the complete cached workflow with internet access blocked. Capture enough evidence to repeat each check, without putting private data into ordinary logs.

**Exit demo:** restore the system into an isolated environment from the documented backup, rebuild the graph, verify accepted facts and citations, and prove withdrawn content stays unavailable.

### M7: pilot and handover

Run a limited pilot with the agreed corpus and at least three intended users. Record task success, time, citation inspection, corrections, review time, and support issues. Triage failures into release blockers, scope restrictions, and later improvements. The product owner accepts the supported scope; the operator accepts the maintenance responsibilities.

**Exit package:** tagged release and changelog, pinned configuration/model inventory, deployment instructions, completed acceptance matrix, known limitations, backup/restore evidence, user guide, operator guide, and named support/ownership arrangements. A demo video can supplement these artifacts but does not replace recovery or access-control evidence.

## 4. Hardware, compute, and cost control

### 4.1 Practical resource allocation

Use the [design's hardware baseline](PROJECT_DESIGN.md#111-hardware-baseline): one 16 GB-class GPU, a small quantized model, CPU parsing, 32–64 GB host RAM, and initially around 250 GB free SSD. An A100 is optional headroom. No dedicated new GPU purchase, fine-tuning cluster, or always-on cloud GPU is assumed.

Reserve school-GPU sessions for benchmarks, integration, and demonstrations. Most developer tests use fixed model-response fixtures; they should not require three GPU allocations. Run extraction batches outside interactive service windows if the GPU cannot keep answer latency within target. If the host is shared, cap its resource usage and obtain a service window rather than assuming exclusive access.

### 4.2 Cost worksheet

No actual budget amount was supplied. These are planning categories, not prices or spending authorization. Fill them with the institution's allocation and the provider's current quoted rates before paid work.

| Cost item | Baseline approach | Estimate method / control |
|---|---|---|
| Student effort | 720 total planned-capacity hours | 576 delivery + 144 contingency; use school accounting only if needed |
| GPU host | Existing school allocation | Record allowed hours, sharing, and any internal charge; new purchase excluded |
| Cloud experiments | Optional, public/synthetic data only | `GPU hours × current hourly rate + storage + transfer`; hard project cap and auto-shutdown |
| Persistent storage | School SSD/volume where possible | Measure source × working-artifact multiplier + models + database; review disk weekly |
| Independent backup | Existing institutional destination | Retention × measured daily change; confirm capacity and restore access |
| Software | Open-source components and school identity/TLS | Check model and distribution licenses; do not assume enterprise features are free |
| Ongoing operations | Named institutional/team owner | Budget maintenance time, patching, restore drills, and handover outside feature work |

Track spend and remaining credits weekly. Save experiment checkpoints/results frequently, stop idle paid resources, and treat credits as a finite balance. Free or educational Colab resources are not a production hosting assumption: Google documents changing availability, runtime termination, and restrictions on web-service use. Use it for bounded interactive experiments. [Colab FAQ](https://research.google.com/colaboratory/faq.html).

Track candidates/page, review minutes/candidate, accepted useful claims/reviewer-hour and GPU-hours/accepted claim. As an illustration only, 5,000 pages × 3 candidates/page × 30 seconds/candidate is 125 reviewer-hours before corrections and annotation. Include this work explicitly in capacity and reviewer agreements. There is still no verified currency budget or host quote. Benchmark English OCR on the required prose, forms and tables; use the existing E5 RapidOCR/VietOCR comparison to shortlist configurations. Vietnamese expansion has a separate future budget.

### 4.3 Scope cuts if resources are tighter

Cut in this order: optional generated prose; elaborate graph visualization; extra question intents; extra ontology types; optional OCR; corpus size/concurrency beyond the agreed minimum. Keep citations, validation, role enforcement, withdrawal behavior, backups, and honest coverage reporting. If no persistent host/operator is available, deliver the validated prototype and handover package while explicitly leaving the internal production release unaccepted.

## 5. Risk and dependency register

Likelihood/impact are initial qualitative estimates. Review weekly and after each milestone. Owners are role placeholders until kickoff.

| ID | Risk / dependency | Likelihood / impact | Trigger to watch | Mitigation / contingency | Owner |
|---|---|---|---|---|---|
| R-01 | Model extracts plausible but incorrect facts | High / High | Low precision, wrong units, unsupported citations | Exact evidence checks, held-out evaluation, manual approval, narrower ontology/model comparison | A |
| R-02 | Table/scan errors propagate into claims | High / High | Missing pages, malformed headers, known form failures | Coverage flags, table-specific labels, reviewed corrections; exclude unsupported pages and defer OCR | A |
| R-03 | GPU access is intermittent or shared | Medium / High | Allocation changes, OOM, long queue | Small baseline model, fixture tests, scheduled batches, bounded public-data cloud experiments | C / IT |
| R-04 | Research host cannot support a persistent service | Medium / High | No stable volume/network/owner | Confirm in M0; seek approved institutional host; production gate stays open | C / IT |
| R-05 | Three-person scope is too large | High / High | Two consecutive milestones consume reserve | Preserve a thin complete workflow, reduce intents/corpus/UI extras, rebaseline hours | B / product owner |
| R-06 | Domain reviewer unavailable | Medium / High | Queue age or labels stall | Schedule review sessions early, use smaller acceptance corpus, escalate domain ambiguities | A / product owner |
| R-07 | Cross-store publication becomes inconsistent | Medium / High | Missing markers, outbox lag, partial graph | Immutable generations, reconciliation, idempotency, fault tests, fail-closed reads | B |
| R-08 | Private data leaks through cloud/logs/backups | Medium / High | Unapproved endpoints or content in logs | Approved boundary, offline test, sanitized diagnostics, role checks, controlled experiment corpus | C / IT |
| R-09 | Identity/TLS access is delayed | Medium / Medium | No provider credentials/integration path by M1 | Use test identity fixtures locally; prioritize IT integration; no private-data launch without auth | C |
| R-10 | False entity merges corrupt many answers | Medium / High | Ambiguous aliases joined automatically | Scope identifiers, review suggestions, retain history, reversible merge projection | B |
| R-11 | Reproducibility differs across Windows/Linux | Medium / Medium | Changed hashes or parser output | Keep Windows reference; version Linux baseline separately after evaluation | A |
| R-12 | Student turnover leaves an unmaintained service | High / High | No successor named by M6 | Shared runbooks, operator training, restore exercise, explicit end-of-project ownership | C / product owner |
| R-13 | Cloud credits expire or costs exceed expectations | Medium / Medium | Credit balance drops or idle compute persists | Hard cap, auto-shutdown, school-host baseline; cloud remains optional | C |
| R-14 | Gold sample is biased or leaks into tuning | Medium / High | Duplicate documents, repeated test-set prompt changes | Freeze split, document-level separation, second annotation subset, disclose uncertainty | A |
| R-16 | BSEE files change between snapshots, or redistribution terms forbid sharing derived data | Medium / Medium | New `Last-Modified`, changed digests, unclear license | Recorded snapshots and optional pins; freeze evaluation snapshots; keep BSEE data out of Git until terms are confirmed | B |
| R-17 | Supervisor focus changes again | Medium / Medium | New sources requested before M2 closes | Keep adapters source-specific and contracts source-neutral; record each change as a decision (specification D-13) | Product owner |
| R-18 | VPI documents arrive late, or may not leave VPI premises | High / High | No documents by M2; processing restricted | Keep public proxies (D-18); keep the stack installable on a VPI-controlled host; report proxy results as such | Product owner |
| R-19 | Oil-specific hardcoding blocks reuse, or abstraction work expands beyond capacity | Medium / High | Core branches on well types, or a second real profile enters backlog | One oil-well profile; narrow generic contracts and registered rules; synthetic portability fixture; defer extra domains/languages | A / product owner |

External dependencies are host allocation, institutional access/identity/TLS, backup storage, domain review, and model-use permissions. Record who is expected to supply each item and by which milestone. Lack of a reply is not approval.

## 6. Delivery cadence and change control

Use one shared board with Backlog, Ready, In Progress, Review, Validate, and Done. A ready item has a requirement ID, owner, acceptance examples, dependencies, and a small estimate. Split work until most items can be completed and reviewed in one or two student work sessions. Limit each student to one major work item at a time.

Meet briefly each week to demo working behavior, review the critical path, inspect risks/remaining hours, and record scope decisions. Re-estimate unfinished work from evidence rather than marking a milestone “90% complete” repeatedly. Track accepted requirement coverage, failing release gates, review backlog, and forecast hours; commit counts are not a progress measure.

Each change receives peer review. Implement tests for meaningful contracts and failure modes, with a small deterministic suite for everyday work and a separate host/GPU integration suite. Keep real-model benchmarks versioned but outside the fast test loop. Every milestone updates the relevant design/current-state sections and stores its verification commands and results.

### Definition of done for a work item

- Its acceptance behavior is demonstrated with an appropriate fixture or real integration check.
- Error handling and access checks are implemented where relevant.
- Another student has reviewed the change and material test evidence.
- Data/schema changes have a migration and rollback/recovery story.
- User-facing behavior and operating instructions are documented.
- Known limitations are recorded; no failing required check is described as a pass.

### Definition of release complete

All Must requirements (FR-01 through FR-13, FR-15, FR-16 and FR-18) have accepted evidence; gates G1–G9 have results; unresolved defects are classified and accepted where permissible; the workload and support limits are published; the product owner and operator accept their respective responsibilities. Security, evidence integrity, and recovery failures block release. The source repository and this design alone do not satisfy that definition.

## 7. Next implementation backlog

Revised after the 27 October repository review. Complete one reviewed evidence-to-answer path before expanding formats, domains or infrastructure. All fixes below are open unless explicitly marked otherwise. Preserve E1–E8 as historical measurements; E9 records the review checks.

| Order | Task | Acceptance artifact | Status |
|---|---|---|---|
| 1 | Resolve specification §13.2 and agree the initial questions, reviewer, host/data boundary, capacity and spending ceiling | One decision record; demonstrator versus internal-pilot acceptance named; one English oil-well profile, core/profile boundary and remaining estimate recorded | Open |
| 2 | Freeze an independent document-level split, gold revision and full matching rubric before tuning | Dataset/gold/scorer manifest, second annotation subset, leakage check; review-time protocol | E4 has 41 development facts; held-out work open |
| 3 | Fix staging/activation, duplicate headers/record IDs and date validation | Invalid replacement cannot displace accepted data; interrupted swap preserves current release; malformed model dates reject cleanly | Reproduced in E9; fixes open |
| 4 | Define shared source/bundle/evidence, registry and claim-revision contracts | One corpus document and synthetic dataset row; scoped identifiers, language tags, MD/TVD, planned/actual, original units and versioned evidence | Ingestion schemas exist; application contracts open |
| 5 | Add deterministic CI and installation/cache checks | 128 main + 4 prototype checks in explicit suites; targeted behavior regressions; configuration-aware cache tests; installed wheel/schema check | Local suites passed in E9; CI/fixes open |
| 6 | Build authenticated review with a minimal source viewer | Server-derived actor, direct-route role checks, real reviewer acceptance/correction, source navigation and measured minutes/claim | Prototype API only |
| 7 | Promote durable jobs, review revisions and exact generation-set validation | Migrations, idempotent leased job, frozen accepted set, completion marker, crash/retry and generation-pinning demo | Prototype generation mechanism exists; production contracts open |
| 8 | Deliver three cited question intents and source withdrawal | Correct answer with exact evidence; unsupported/missing cases; immediate retirement block and restore tombstones | E4 development QA only |
| 9 | Demonstrate oil-well cross-source identity and profile portability | One well linked to dataset/report evidence; small synthetic profile fixture loads/validates/dispatches without core edits | Open; AK-3 is not a BSEE well |
| 10 | Compare extraction/model/OCR and retrieval approaches on frozen inputs | False-negative trace by stage; passage/claim/graph baseline; full-context scoring, latency/memory and review cost | E4/E5 development results; independent comparison open |
| 11 | Run host pilot, blocked-network workflow and independent restore | Approved data boundary, workload results, access/failure gates, known limits, named operator and handover | Open |

The main [README](../README.md) remains the setup/CLI entry point. Do not rerun `publish` simply to check documentation: it writes the selected bundle. Fresh `run` requires PDF/model acquisition and can take time; first inspect existing artifacts and use an isolated named run for experiments.

## 8. Planning decisions still to close

Scope questions for the supervisors are in [specification §13.2](PROJECT_DESIGN.md#132-open-questions-for-supervisor-meetings). This table holds the planning and operating decisions.

| Decision | Needed by | Why it matters |
|---|---|---|
| Actual weekly availability and any deadline | M0 | Converts person-hours into a realistic calendar |
| Exact host/GPU allocation and service-hosting permission | M0/M1 | Determines runtime, access windows, and whether production hosting is possible |
| Team-wide versus document-specific access | M0 | Current scope assumes all readers may see all published documents |
| Domain reviewer and initial question catalogue | M0/M2 | Defines ontology semantics and an answerable product boundary |
| Login provider, TLS/network route, backup destination | M1, finalized by M6 | Avoids late integration and operational blockers |
| Model/checkpoint/license and measured context/concurrency | M2 | Determines quality, memory use, and actual hardware fit |
| Spending ceiling and cloud-account owner | Before paid use | Prevents accidental reliance on unbounded cloud resources |
| Retention, support hours, operating owner | Before M7 acceptance | Makes the internal service maintainable after handover |
| BSEE redistribution terms | Before committing any BSEE-derived fixture or sharing bundles | The listed terms are a disclaimer, not an open license |
| Snapshot-level review of datasets (specification D-14) | M3 | Determines the review workload and how dataset claims enter the graph |

The specification and this plan remain usable with clearly labelled assumptions; production implementation must close the relevant decisions at their stated gates.

Deliver the public-data demonstrator independently of private-data admission. Keep the internal-service target, but do not report that target accepted without host, identity, recovery and operator evidence. The unified [progress report](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) preserves the team's reporting voice and summarizes the state of all project workstreams, their evaluation results and the integration plan.
