# E4: Architecture prototype on AK-3

**Current direction:** English-first oil-well delivery on a reusable core (D-26/D-27). This record preserves the experiment/review as run; profile-driven extraction and QA remain integration work. See the [specification](../PROJECT_DESIGN.md#44-core-and-domain-profile-boundary).

| | |
|---|---|
| **Date** | 25 October 2026 |
| **Question** | Do the target components (llama.cpp, PostgreSQL, Neo4j, FastAPI) fit together for extraction → validation → review → graph generation → cited QA, and where do errors come from? |
| **Requirement** | SR-02, SR-04, SR-16; specification §4–§8 |
| **Input** | 15 of 60 chunks of the AK-3 report (`gdr882_ak3_eowr`) from the published bundle |
| **Code** | [`prototype/`](../../prototype/README.md), with its own environment and Docker services |
| **Gold** | [`prototype/gold/`](../../prototype/gold/): 41 facts, 31 questions; single annotator, AI-assisted |
| **Outputs** | [`prototype/results/`](../../prototype/results/): current scores; `history/` for earlier runs (file map below) |
| **Status** | Concluded for the stack; follow-up on prose extraction recall is backlog item 6 of the [plan](../DEVELOPMENT_PLAN.md#7-next-implementation-backlog) |

> **Test build, not the real system.** Results are evidence for or against design choices. They are not acceptance results (specification §12), and they must not be quoted as system performance: the slice is small, the gold set is single-annotator, and the prompt was revised on the same slice (no held-out test). The prototype predates the VPI requirements: it has one module, no entity registry, and no interpretation claims.

## Setup (25 October 2026)

| Item | Value |
|---|---|
| Host | Development laptop: Intel i5-1340P, 16 GB RAM, no usable GPU; Docker Desktop VM with 8 GB and 16 CPUs |
| Services | `docker-compose.yml`, images pinned by digest: Neo4j 5.26 Community, PostgreSQL 16 (alpine), llama.cpp server (CPU, 8 threads, 8K context). Localhost only, throwaway credentials |
| Model | Qwen2.5-3B-Instruct, Q4_K_M GGUF (2.1 GB, SHA256 `626b4a66…5c62d`). Qwen research licence: acceptable for this test, to be re-checked before any production choice. About 34 prompt tokens/s and 14 generated tokens/s |
| Application | Python 3.12 in `prototype/.venv` (`requirements.txt`), separate from the locked ingestion environment |
| Source | **AK-3 report only** (`gdr882_ak3_eowr`). BSEE is a separate track and not part of this test |
| Slice | 15 of 60 chunks: the 8-chunk pilot (executive summary, drilling summary, both casing tables, survey table, rig-time table, temperature text and table) plus the 7 other chunks stating the same facts |
| Gold | `gold/ak3_facts.json`: 41 facts across 14 ontology properties; `gold/questions.json`: 31 questions. AI-assisted, single annotator, not checked by a domain expert |

## Flow under test

1. **Load:** AK-3 document and chunks into Neo4j.
2. **Extract:** each text chunk, or each table row under its caption and header, goes to llama.cpp, which returns JSON-schema-constrained typed claims. For table rows the evidence quote is the row itself. Every candidate is stored in PostgreSQL.
3. **Validate:** deterministic checks. Known property, unit and qualifier; casing size or depth where required; quote verbatim in the chunk; value a single number present in the quote; dates supported by the quote, with the year present in the passage. Failures are recorded as rejections by actor `validator`.
4. **Review:** the remaining candidates wait in the queue (`GET /review-items`). Decisions are posted through `POST /review-items/{id}/decisions`; a second decision on the same item returns 409. The reviewer here is a **stand-in** (see below).
5. **Project and activate:** accepted claims are written to Neo4j as a numbered generation (`(:Claim)-[:ABOUT]->(:ReportWell)`, `(:Claim)-[:SUPPORTED_BY {quote}]->(:Chunk)`). The generation is checked (every claim has evidence), then the PostgreSQL publication pointer is switched to it.
6. **Answer:** `POST /questions` pins the active generation. The model proposes a plan; code checks the well is named in the question, derives the qualifier from the ontology and wording, resolves the well, and runs a fixed read-only Cypher template. The answer is either values with citations (document, chunk, page, quote), "no accepted knowledge", or an abstention with a reason.

**Reviewer stand-ins.** *Oracle* accepts a candidate only if it matches a gold fact; it models a careful human who checks the source. *Accept-all* models no review. Real reviewer accuracy and time are not measured here.

## Extraction runs (before review)

| # | Change | Chunks / gold in scope | Candidates → valid | Precision | Recall |
|---|---|---:|---:|---:|---:|
| 1 | Pilot, prompt v1 | 8 / 38 | 17 → 11 | 0.64 | 0.16 |
| 2 | Prompt v2: one claim per table row, well-name rule, depth required | 15 / 41 | 24 → 15 | 0.67 | 0.17 |
| 3 | Tables sent row by row (deterministic split) | 15 / 41 | 49 → 28 | 0.79 * | 0.54 |
| 4 | Run 3's outputs re-validated with the date-year rule (no new model calls) | 15 / 41 | 49 → 25 | 0.88 | 0.54 |
| **5** | **Prompt v4: table row is the evidence; "value is only the number"; caption decides planned/actual; one worked example on an invented table** | **15 / 41** | **43 → 29** | **0.97** | **0.68** |

\* Run 3 was first reported as 0.89 because the scorer compared dates with a 0.5% numeric tolerance ("2022-08-26" matched "2016-08-18"). Fixed and covered by `test_ontology.py`; history files keep the corrected value.

Result files: runs 1–4 are `prototype/results/history/run<N>_extraction_*.json` (run 3 also has its model log, `run3_extraction.log`). Run 5 is `prototype/results/extraction_run1.json`: the scorer names files by database run ID, and the database was reset before run 5. An early QA pass with accept-all review, before run 5 and before the QA scoring was revised, is `history/pre_run5_qa_accept_all.json` (17/31 correct).

Run 5 took 10 minutes on CPU (39 model calls; median 15 s, maximum 71 s). Its only false positive: the 19 days from spud to rig release filed as `drilling_days`. Its misses are mostly **prose facts**: total depth, planned depth and duration, maximum measured temperature (all in the executive summary), the TG-2 and TG-4 depths, the API number, and the ground elevation. Survey and casing rows are now mostly correct.

What the validator caught (errors that never reached review): invented years for dates written without a year; survey rows proposed as casing depths; whole table rows put in `value`; a mud temperature proposed as the maximum measured temperature without a depth; paraphrased quotes.

## Review, generations and QA (run 5)

Result files: `prototype/results/qa_reviewed.json` (generation 1) and `qa_no_review.json` (generation 2).

| | Generation 1: reviewed (oracle) | Generation 2: no review (accept-all) |
|---|---:|---:|
| Queue → accepted / rejected | 29 → 28 / 1 | 29 → 29 / 0 |
| Second decision on a decided item | refused (409) | refused (409) |
| Generation checks (claims, evidence links) | passed (28, 28) | passed (29, 29) |
| Gold facts in the graph | 28 / 41 | 28 / 41 (+1 wrong claim) |
| **End-to-end correct** (extraction + QA) | **19 / 31** | 19 / 31 |
| **QA layer correct** (given what is in the graph) | **31 / 31** | 30 / 31 |
| Answers with citations; quotes verbatim in the chunk | 11 / 11; 11 / 11 | 12 / 12; 12 / 12 |
| Answers containing no wrong value | **11 / 11** | 11 / 12 |
| Graph unchanged after both injection prompts | yes | yes |
| Latency per question: median / p95 / max | 4.3 / 6.0 / 9.0 s | 4.9 / 6.2 / 7.5 s |

End-to-end by question kind (reviewed): answerable 9/18, paraphrased 2/4, not stated 3/3, unsupported 4/4, injection 1/2. Every end-to-end failure is a fact extraction did not produce. In those cases the system answered "no accepted knowledge", or "unknown well" for TG-2 and TG-4 (no accepted claims, so entity resolution finds no such well), and never invented a value.

Scoring note: the QA-layer metric accepts either honest no-answer when the fact is absent. This was widened after the first scored pass, which had counted "unknown well" as wrong; the reasoning is recorded in `evaluate_qa.py`.

Switching the publication pointer between generations 1 and 2 changed the answers immediately, without rebuilding anything. This is the activation and rollback mechanism of design §4.3, at small scale.

## What this tells us about the architecture

1. **The stack works end to end on CPU.** Neo4j, PostgreSQL, llama.cpp and FastAPI run on a laptop. Extraction takes about 15 s per passage; answers take about 4–6 s.
2. **Evidence-first holds.** Every published claim and every answer traces to a verbatim quote and page. Validation alone removed most wrong candidates before review.
3. **Review matters even at 97% precision.** Without it, a wrong value reached an answer.
4. **Deterministic code around a small model is what made it work.** Table rows were split by code; the plan's qualifier, well name and casing size were checked by code; queries were fixed templates. The 3B model alone mislabelled qualifiers and intents often.
5. **The bottleneck is extraction recall on prose (0.68 overall).** Next experiments:
   - first freeze a separate, deduplicated, document-level held-out set and matching rubric; keep this slice as development data;
   - split long paragraphs into sentences;
   - make a second pass on executive summaries;
   - try a 7–8B model on the school GPU;
   - report held-out results once the prompt is fixed; do not tune on that set.

## Not tested

**27 October follow-up:** [E9](E9-repository-review.md) records passing ontology tests alongside reproduced calendar-date defects and a code finding that generation validation does not establish exact accepted-set completeness. The count-based injection fingerprint also does not prove that graph properties were unchanged. E4's original observations above remain historical; these limitations must be fixed/tested before application promotion.

- Human reviewers, and real reviewer time.
- The UI.
- Authentication and roles.
- Concurrent users.
- The "no active generation" error path.
- Backups and restore.
- Throughput on a GPU.
- Documents other than AK-3, and other ontologies.
