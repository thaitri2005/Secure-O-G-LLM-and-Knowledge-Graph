# Track B log

Every finding, decision, design choice and experiment of Track B goes here the same day. Entries are never renumbered or deleted. When an entry is replaced, a later entry says so and names it.

| Prefix | Kind | What it records |
|---|---|---|
| **B-F** | Finding | Something learned from reading or from a run, with its source |
| **B-D** | Decision | What we chose, and why |
| **B-C** | Design choice | How a part is built: a setting, a prompt rule or an interface |
| **E** | Experiment | A link to the record in [`docs/experiments/`](../../experiments/README.md), plus one line on the outcome |

## Current state

| Topic | Current answer | Entry |
|---|---|---|
| Data this stint | AK-3, 56-32 and 68-32 end-of-well reports; four AK-3 daily-report attachments; 78-32 as an unseen report | B-D01, E24, E25 |
| Quality yardstick | Development only: the prototype's 31 questions and simulated sets. The expert set, when it arrives, is the real one | B-D01, B-D22 |
| Efficiency | Calls, tokens, seconds and cost per page and per question on every run | B-D02 |
| What runs | Questions over time on daily reports: event graph ([E28](../../experiments/E28-event-graph.md)). Others: retrieval with Qwen3-8B (thinking off), citations and values checked in code; BM25 routed by well, top 5; questions naming several wells use per-well fusion, top 10, evidence first; daily reports also filter by date. 28/31 prototype, 31/40 simulated, 23/36 held out ([E26](../../experiments/E26-routing-and-strict-facts.md)) | B-D23, B-D26 |
| Graphs | **Event graph in use:** 22/35 and 19/23 against 5/35 and 4/23 for plain RAG, on questions chosen to suit it. **Per-well fact graph in use for end-of-well answers:** ties plain RAG on new lookup questions so far (E23, E26, E27); questions across wells are where it should help | B-D26, B-D29 |
| Bases to run | neo4j-graphrag-python ([E16](../../experiments/E16-neo4j-graphrag-python.md), [E20](../../experiments/E20-well-fact-sheet.md)) and LightRAG ([E19](../../experiments/E19-lightrag.md), with K2 [E21](../../experiments/E21-lightrag-k2.md)) run and not adopted as bases; neo4j-graphrag is the extractor for the optional fact sheet | B-D14, B-D18, B-D21, B-D24 |
| What to adopt | Solutions close to our description, which we then improve | B-D08 |
| Extraction defaults | One pass, constrained JSON, ontology slice only, cache by chunk hash; citations checked in code | B-C01 to B-C04, B-C07 |
| LLM | Qwen3-8B (thinking off) answers best; Qwen3-4B second; Qwen2.5-7B and Llama-3.1-8B abstain and are dropped | B-D06, B-D14 |
| Retrieval | BM25 routed by well; per-well fusion with Qwen3-Embedding-0.6B for questions naming several wells; date filter on daily reports | B-D23, B-C21, B-C22 |
| Compute | Desktop RTX 4080 SUPER with llama.cpp (`-c 32768 -np 1`), one request at a time for measurements; Neo4j in Docker | B-F16, B-C09, B-C10 |
| Daily reports | Lookups: date filter 14/26, with the event graph's planner in front 17/26. Totals over time: event graph. Form headers, inventory and parameters need K1 version 1 ([note for Khai](note-for-track-A-daily-reports.md)) | B-F35, B-F36, B-C22, B-D26 |
| Next | **The second build: one connected application** ([specification §4.6](../../PROJECT_DESIGN.md#46-second-build-one-connected-application)). Track B's part, in the [plan's task list](../../DEVELOPMENT_PLAN.md#7-what-to-do-now): answers on K1 version 1 (E32), reading the stores, the lane interface, the fact graph as nodes for Neo4j, the coordinator (E33), computed results inserted by code, the reasoning probe (E34). Still waiting on the expert questions and the purpose of use (Q13) | B-D36 to B-D38, B-C35, [next-runs](next-runs.md) |
| Coordinator | **Built, not yet measured** (`graphrag/coordinator.py`): one framing call, lanes chosen in code from a fixed table, fixed fallback, an exact-answer switch ([specification §8.1](../../PROJECT_DESIGN.md#81-the-coordinator-and-its-lanes)). A result computed by code is reported by code, with no answer call. Adopted only if E33 matches the hand-routed scores on the 221 pooled questions; E33 needs the desktop GPU. Replaying E28's recorded plans with code reporting gives 33 of 35 and 22 of 23, against 27 and 19 recorded (no model call) | B-D32, B-D36, B-C37 to B-C39, B-C43, B-F61 |
| Lanes | `graphrag/lanes.py`: passages, well facts and events behind one function shape, each returning the same evidence; settings are the baseline's | B-C37 |
| Graph model | One graph, two regions joined at `Well` and `Chunk` ([specification §8.5](../../PROJECT_DESIGN.md#85-the-graph-nodes-and-relationships)). Event region in Neo4j (Track C). Fact region exported as nodes and relationships for Track C's loader: [`E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json), 216 facts of 5 wells | B-C35, B-C40, B-F60 |
| Application | FastAPI backend and React frontend, read path first; `graphrag` is its library; the local UI stays a developer tool. **Backend read path built** on Hung's behalf (`backend/`, contract and example responses for the frontend); it reads files, not the stores. **Frontend built** (`frontend/`, React), on the contract and the example responses; redone in plain language for non-developers (B-C47); not yet run against a real model, nor used by anyone outside the team | B-D37, B-D39, B-C44 to B-C47 |
| Ontology (K2) | Version 1.2: adds `rig`, `drilling_contractor`, and casing-spec, key-value and casing-item mappings ([k2_eowr_v1.json](../../../configs/ontology/k2_eowr_v1.json)). Casing mappings checked on 6 unseen reports ([E29](../../experiments/E29-table-mappings-across-reports.md)); no further ontology work (B-D25) | B-D17, E27, E29 |
| Answer records (K4) | Version 0.2 for coordinator runs (lanes, mode, kind of question, framing model, B-C41). Version 0.1: [`k4_answer_record.schema.json`](../../../schemas/k4_answer_record.schema.json), written by `python -m graphrag.k4 <run>`; current files: `E26_plain_routed.k4.jsonl`, `E27_heldout_dates_bm25.k4.jsonl`, `E28_heldout_graph.k4.jsonl`. Computed answers cite source events (`how: event_graph`) | B-C18, B-C21, B-C24 |
| Questions | All simulated except as noted: prototype 31; probe 9; simulated 40 (s02's gold to fix in the next version); held out 36; AK-3 daily 30 and daily held out 26. None is expert-reviewed | B-C14, B-D22, B-F34 |
| Vector store | pgvector inside Track C's PostgreSQL, Hung's proposal; BM25 stays alongside it | B-D30 |

## 2026-10-30

**B-F01 (finding).** A graph does not help on simple fact questions.

- GraphRAG-Bench (ICLR 2026) finds plain RAG equal to or better than GraphRAG on simple fact retrieval.
- Graphs help on multi-step reasoning and as the corpus grows.
- Many of our questions are single-fact lookups such as "what total depth did AK-3 reach?". Every base must therefore be compared with plain vector RAG, and combined vector and graph retrieval is the likely winner.
- Source: [arXiv 2506.05690](https://arxiv.org/abs/2506.05690v3).

**B-F02 (finding).** On ~7B models, invalid structured output is the main failure.

- A study running Microsoft GraphRAG on local 7B models reports broken JSON and degenerate repetition.
- Secondary sources say constrained decoding (a JSON schema or grammar) matters more than which small model is used.
- Sources: [arXiv 2605.20815](https://arxiv.org/pdf/2605.20815); [structured extraction](https://bestllmfor.com/best/structured-data-extraction-json/) (unverified).

**B-F03 (finding).** LightRAG's own documentation recommends large extraction models.

- It names Qwen3-30B-A3B-Instruct as the "reasonable minimum" for local extraction.
- It says the query model should be stronger than the extraction model.
- It warns that models slower than about 50 tokens per second can time out on dense chunks.
- This conflicts with the ~7B limit (D-37), so LightRAG on a ~7B model is a real test, not a formality.
- Source: [LightRAG README](https://github.com/HKUDS/LightRAG).

**B-F04 (finding).** neo4j-graphrag-python matches the ontology-injection requirement directly.

- Its schema takes node types, relation types and allowed patterns.
- `additional_*` flags decide whether undefined types are kept or pruned.
- Structured output is supported.
- A lexical graph links Document and Chunk nodes.
- Entity resolution merges nodes with the same label and name.
- Extraction runs once per chunk.
- Source: [KG builder guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html).

**B-F05 (finding).** neo4j-labs/llm-graph-builder is a finished application close to our M4 target.

- It covers upload, schema settings, seven chat modes, sources in answers and per-user token limits.
- It runs on FastAPI with a React frontend, uses Neo4j, and accepts Ollama and OpenAI-compatible models.
- Apache-2.0.
- Source: [README](https://github.com/neo4j-labs/llm-graph-builder).

**B-F06 (finding).** RAGFlow offers two extraction modes: "Light" (LightRAG prompts) and "General" (GraphRAG prompts with repeated extraction rounds, known as gleaning).

- Its documentation says Light uses fewer tokens.
- Graph construction is token-heavy, especially with entity resolution and community reports.
- This confirms where the cost goes: extra extraction rounds, entity-description summaries and community reports.
- Sources: [RAGFlow docs](https://ragflow.io/docs/construct_knowledge_graph), [DeepWiki](https://deepwiki.com/infiniflow/ragflow/6.4-graphrag-and-knowledge-graph-construction).

**B-F07 (finding).** fast-graphrag injects a domain cheaply.

- Its configuration is a domain description, a list of entity types and example queries.
- Retrieval uses personalized PageRank.
- It claims (self-reported) to be 6× cheaper than Microsoft GraphRAG on one book.
- Source: [README](https://github.com/circlemind-ai/fast-graphrag).

**B-F08 (finding).** Youtu-GraphRAG uses the schema at both extraction and query time.

- A seed schema bounds what is extracted and guides how a question is split into sub-queries.
- It claims (self-reported) up to 90% fewer tokens.
- Its licence is Tencent's own text and is not yet read.
- Source: [arXiv 2508.19855](https://arxiv.org/abs/2508.19855).

**B-F09 (finding).** MiniRAG targets small models.

- It runs on Qwen2.5-3B and Phi-3.5-mini.
- Retrieval relies on graph structure instead of a strong query model.
- The repository has been inactive since October 2025.
- Source: [arXiv 2501.06713](https://arxiv.org/pdf/2501.06713v2).

**B-F10 (finding).** Small LLM candidates.

| Model | Size | Note |
|---|---|---|
| Qwen3-4B-Instruct-2507 | 4B | Reported 98.9% valid JSON (unverified) |
| Qwen2.5-7B-Instruct | 7B | Continuity with the prototype, which used Qwen2.5-3B |
| Llama-3.1-8B-Instruct | 8B | Slightly above "about 7B" |
| Qwen3-8B | 8B | Slightly above "about 7B" |

Which of these OpenRouter serves is not yet checked.

**B-F11 (finding).** Embedding candidates.

| Model | Note |
|---|---|
| Qwen3-Embedding-0.6B | Strong for its size |
| bge-m3 | Multilingual, useful if Vietnamese documents come later |
| EmbeddingGemma-300M | Smallest; possible |

Scores come from secondary rankings, so we choose by retrieval recall on our own questions. Sources: [theairankings](https://theairankings.com/best-embedding-models/), [premai](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/).

**B-D01 (decision).** Start small.

- Begin with the 15 AK-3 EOWR chunks from the prototype, then the whole AK-3 EOWR; daily reports come only after a base is chosen.
- Use the prototype's 31 questions and the E10 gold facts as the yardstick.
- *Why:* the supervisor asked to begin on one short document (D-44), and small runs are cheap to repeat.

**B-D02 (decision).** Efficiency is a headline metric.

- Every run records LLM calls, input and output tokens, wall-clock seconds, and cost per page and per question, next to quality.
- *Why:* large runs will be on ~7B models within booked GPU slots, so the cost per page decides what is feasible (D-38).

**B-D03 (decision).** Build plain vector RAG first, on the same chunks and questions.

- It costs nothing to index beyond embeddings.
- Every base must beat it on quality or justify its extra cost.
- *Why:* B-F01.

**B-D04 (decision).** Run neo4j-graphrag-python first and LightRAG second.

- Learn from llm-graph-builder (application), RAGFlow (cost modes), fast-graphrag and Youtu-GraphRAG (cheap ontology injection) and MiniRAG (small models).
- Skip Microsoft GraphRAG (token-heavy), KAG and Graphiti as bases.
- *Why:* B-F03 to B-F09; [survey](survey.md).

**B-D05 (decision).** Ask the supervisor whether 8B models count as "about 7B".

- *Why:* Qwen3-8B and Llama-3.1-8B are the obvious candidates just above the limit.

**B-C01 (design choice).** One extraction pass per chunk.

- No gleaning rounds, no entity-description summaries, no community reports.
- Add any of them later only if a run shows the quality gain is worth the calls.
- *Why:* B-F06; these are the main token sinks.

**B-C02 (design choice).** Constrained JSON output.

- Use the provider's JSON-schema mode where OpenRouter supports it; use a grammar (XGrammar in vLLM) on local serving.
- Count invalid outputs and retries as a metric.
- *Why:* B-F02.

**B-C03 (design choice).** Each extraction prompt carries only the ontology slice relevant to the chunk's section, not the whole ontology.

- *Why:* shorter prompts on every call, and the specification's slicing design (§6.2).

**B-C04 (design choice).** Cache every model call by chunk hash, prompt version and model.

- Reruns and comparisons then cost nothing for unchanged chunks.
- *Why:* efficiency; LightRAG and the prototype already do this.

**B-D06 (decision; answers B-D05).** 8B models count as "about 7B".

- Qwen3-8B and Llama-3.1-8B-Instruct join the LLM candidates.
- *Why:* confirmed by Tri on 30 October 2026.

**B-D07 (decision).** Every licence in the survey is acceptable if we give proper credit, including Youtu-GraphRAG's Tencent licence.

- Copied or adapted code keeps its copyright notice.
- The source repository, commit and licence are recorded in a `NOTICE` file next to the code.
- *Why:* Tri's decision on 30 October 2026.

**B-D08 (decision).** Adopt only what is close to our description, then make it better.

- We look only at solutions close to the 28 October description:
  - ontology-guided extraction with small models;
  - chunk provenance;
  - graph and vector retrieval;
  - a usable application.
- We take them over and improve them on drilling reports, for example with ontology slicing, cost per page, tables and review by exception.
- neo4j-labs/llm-graph-builder is studied whenever we need a part it already has, such as schema settings, chat modes or token limits. We do not adopt it wholesale.
- *Why:* the supervisor asked to take over an existing pipeline and improve it (D-36, D-41).

## 2026-10-30 (evening): first code and the retrieval baseline

**B-C05 (design choice).** Code lives in [`graphrag/`](../../../graphrag/README.md).

| Module | Contents |
|---|---|
| `client.py` | Model client covering B-C02 and B-C04, plus the private-data guard (FR-28) |
| `retrieval.py` | BM25, dense and fusion retrieval |
| `scoring.py` | The prototype's answer rules, so results compare with E10 |
| `baseline.py` | Command line for retrieval and answer runs |

- Endpoints are configured in `configs/graphrag/endpoints.json`.
- Tests are in `tests/test_graphrag.py` (12 tests, no model calls).

**B-F12 (finding).** PyTorch on this laptop (Intel i5-1340P, 16 GB, CPU only) is unusably slow for embeddings.

- One batch of eight 200-token passages through bge-small (33M parameters) took 13–21 s, where about 0.1 s is normal.
- llama.cpp on the same CPU embeds about 18–80 tokens per second with Qwen3-Embedding-0.6B. The rate depends on what else is running on the laptop.

**B-C06 (design choice; follows B-F12).** All models, embeddings included, are served through OpenAI-compatible endpoints (llama.cpp locally) and called through the one client.

- The PyTorch embedding path was removed.
- *Why:* serving through endpoints is faster here, and it is how deployment will work (vLLM or llama.cpp on the school GPUs).

**B-F13 (finding).** llama.cpp's Vulkan backend on the Iris Xe integrated GPU runs out of device memory even for a 0.6B embedding model.

- Running with `--device none -ngl 0`, which uses the CPU only, works.

**B-F14 (finding).** On the AK-3 report, BM25 retrieves better than dense embeddings, and is about 6,000× cheaper to index. See [E14](../../experiments/E14-plain-rag-baseline.md).

| Pool | Retriever | Hit@5 | Mean reciprocal rank |
|---|---|---|---|
| 60 AK-3 chunks | BM25 | 1.00 | 0.81 |
| 60 AK-3 chunks | Qwen3-Embedding-0.6B | 0.78 | 0.65 |
| 60 AK-3 chunks | Fusion of both | 0.87 | 0.73 |
| 372 chunks (three reports) | BM25 | 0.78 | 0.59 |

- Our questions name wells, depths and casing sizes, so they are keyword-heavy, and BM25 matches those keywords exactly.
- Fusion with weak dense results drags BM25 down.
- Adding other reports hurts BM25. Filtering by document or well, using the ID payload (§5.11), will matter before the corpus grows.

**B-D09 (decision).** Use BM25 as the retriever for the answer baseline. Do not run dense retrieval over the 372-chunk pool on this laptop.

- Indexing that pool would take over an hour at the speed measured here.
- Dense and hybrid retrieval are revisited on OpenRouter or the school GPUs, where embedding is cheap.

**E14 (experiment).** Plain RAG baseline: [E14](../../experiments/E14-plain-rag-baseline.md).

- BM25 over the AK-3 report, the top 5 chunks and Qwen3-4B-Instruct-2507 (local CPU) answered **21/31** correctly. The E10 prototype answered 23/31.
- All 9 questions that should get no answer were refused.
- There were 0 invalid JSON outputs.
- Each question used about 1,400 prompt tokens and about 100 s on the laptop.

**B-F15 (finding; from E14).** On one report, the 4B model's reading is the bottleneck, not retrieval.

- Every gold fact was among the 5 passages. Seven misses were the model saying "not stated", four of them on table chunks.
- Model-written citations are unreliable: quotes were verbatim in only 5 of 15 answers.

**B-C07 (design choice; from B-F15).** Citations are attached or checked in code from the retrieved chunk IDs, never taken on trust from the model. Dates and numbers are normalized in code after the call.

**B-D10 (decision).** Next, run neo4j-graphrag-python on the same 60 chunks, questions and model, and compare it with E14 on correctness, citations, tokens and time.

- Rerun E14 with the B-C07 checks and *k* = 3 at the same time, so that the baseline is as strong and as cheap as it can be.
- Speed and cost comparisons move to OpenRouter once the key is set. This laptop is shared with other work, so its timings are not comparable between runs.

## 2026-10-31

**B-D11 (decision).** Track B runs move to a bigger machine or to OpenRouter. The old laptop's downloaded models were deleted, about 7 GB:

- `data/interim/models/`;
- the Hugging Face cache copies of Qwen3-Embedding-0.6B and bge-small.

How to set up a new machine, and the exact next steps, are in [CLAUDE.md](../../../CLAUDE.md).

- *Why:* the laptop was too slow to compare runs (B-F12, E14), and a new session must be able to continue from the repository alone.

## 2026-10-31 (afternoon): desktop GPU and E15

**B-F16 (finding).** A desktop GPU makes Track B runs cheap enough to repeat.

- Machine: RTX 4080 SUPER 16 GB, Ryzen 9 9900X, 32 GB. llama.cpp b12015 (CUDA 12.4 Windows build), both models fully on the GPU, about 4 GB of video memory together.
- The E14 answer run takes 25 s instead of 3,714 s on the laptop; indexing AK-3 with Qwen3-Embedding-0.6B takes 1.1 s instead of 614 s.
- E14 reproduced on this machine at 21/31 with identical prompt tokens. GPU decoding is not bit-for-bit repeatable: completion tokens differ by about 0.5% between runs, so a difference of one question is noise.

**B-C08 (design choice; implements B-C07).** Citations and values are checked in code after the answer call.

- `graphrag/citations.py`: a model citation stands only if the chunk was retrieved and holds the quote; otherwise it is attached from the retrieved chunk holding the quote, then the value; otherwise the answer has no supported citation.
- `scoring.normalize`: dates to `YYYY-MM-DD`, no thousands separators, duplicate values merged. Raw model values stay in the result file.

**E15 (experiment).** Baseline with the code checks: [E15](../../experiments/E15-baseline-checks-in-code.md).

- BM25, *k* = 5, Qwen3-4B: **22/31** (E14: 21/31). Date normalization fixed q07.
- Citations supported after the check: 16/17 answers, against 7/17 verbatim model quotes. The one unsupported answer is the one wrong answer to an unanswerable question (q25).
- *k* = 3: 20/31 with 37% fewer prompt tokens.
- Retrieval: dense quality unchanged from E14; on the 372-chunk pool, fusion lifts hit@5 from 0.78 to 0.91.

**B-F17 (finding; from E15).** An answer with no supported citation is a usable signal to withhold it: in E15 it flagged exactly the one hallucinated answer and nothing else.

**B-D12 (decision; from E15).** The baseline stays at BM25 with *k* = 5 on one report; fusion of BM25 and Qwen3-Embedding-0.6B is used once a pool holds more than one report.

- *Why:* *k* = 3 loses two answers for 37% fewer tokens; fusion is the only retriever that holds up against distractor reports (0.91 against 0.78).
- Replaces the part of B-D09 that kept dense retrieval off: it is cheap on the GPU.

**B-D13 (decision).** Next, in order:

1. Withhold answers without a supported citation, and measure it.
2. Run the baseline with Qwen3-8B and Qwen2.5-7B-Instruct locally, to size how much of the reading gap is the model.
3. Run neo4j-graphrag-python as E16 (B-D10 step 2).

## 2026-10-31 (evening): neo4j-graphrag-python, models and a correction

**B-F18 (finding; replaces B-F17, which was wrong).** A supported citation does not mean a right answer.

- B-F17 said the one unsupported citation in E15 was the made-up answer (q25). It was q19's correct answer, flagged because `1955` did not match `1,955` in the passage. q25's wrong value, 0.25, is in the cited survey table, on other rows, so the check passed it.
- After the check learned to ignore thousands separators, every E15 answer had a supported citation; withholding unsupported answers changed nothing (22/31, [E17](../../experiments/E17-model-sweep.md)). The E15 record carries a correction note.

**B-C09 (design choice).** Track B services and environment.

- Neo4j 5.26 with APOC runs from `configs/graphrag/docker-compose.yml` (APOC is needed by neo4j-graphrag's writer). The prototype's compose file is unchanged; the two share ports, so run one at a time.
- neo4j-graphrag 1.23 needs `pypdf>=6.19`; the main environment pins 6.1.1 for Track A. Its runs therefore use a separate `.venv-graphrag` from `requirements-graphrag.lock.txt`. `graphrag/baseline.py` still runs in the main `.venv`.
- llama-server runs with `-c 32768 -np 4` (8k context per slot); `-c 8192` was too small for extraction prompts.

**B-F19 (finding).** Parallel requests to llama.cpp make results non-repeatable.

- Three cold runs of the same extraction with 4 parallel requests gave recall 0.54, 0.85 and 0.85; one request at a time gave 0.854 three times, bit for bit.
- Server settings matter too: the same sequential answer run scored 22/31 and 23/31 under two context settings.

**B-C10 (design choice; from B-F19).** Measurement runs send one request at a time, and each record states the server settings. `neo4j_kg.py` defaults to `--concurrency 1`; `baseline.py` is already sequential.

**E16 (experiment).** neo4j-graphrag-python on AK-3: [E16](../../experiments/E16-neo4j-graphrag-python.md).

- The library's default prompt with Qwen3-4B: recall **0.85** of the 41 gold facts, 72% right where gold has the key, about 2 calls, 4,500 tokens and 3 s per page, 0 invalid JSON. E10's own pipeline: recall 0.73 at higher precision.
- The E4 domain rules raised precision (0.84) but cut recall to 0.44; one added context sentence cut it to 0.37; Qwen3-8B as extractor gave 0.51.
- Adding the extracted facts under each passage cost 29% more prompt tokens and lowered the 4B model's answers from 23/31 to 21/31; with Qwen3-8B it stayed at 28/31.

**B-F20 (finding; from E16).** Small-model extraction is fragile: one prompt sentence moves recall between 0.37 and 0.85, and a bigger model can be worse. Prompt tuning on 41 facts would overfit.

**E17 (experiment).** Answer models and multi-report retrieval: [E17](../../experiments/E17-model-sweep.md).

- BM25, top 5, AK-3: Qwen3-8B (thinking off) **28/31**, Qwen3-4B 23/31, Llama-3.1-8B 10/31, Qwen2.5-7B 8/31. The last two abstain on nearly every answerable question.
- Three reports, Qwen3-8B: BM25 22/31, fusion **26/31**.

**B-D14 (decision; from E16 and E17).**

1. The plain RAG baseline is now **Qwen3-8B with thinking off**, BM25 on one report and fusion across reports. It answers 28/31 on AK-3 and is the bar for every base.
2. **neo4j-graphrag-python is not adopted as the base on this evidence.** Its graph does not improve answers on these questions. Its schema handling and provenance remain the reference for how a graph should be built if one is needed.
3. Qwen2.5-7B and Llama-3.1-8B are dropped as answer models for this harness.

- *Why:* E16 and E17. On single-fact questions over one or three reports, reading by a capable model beats an extracted graph (as B-F01 predicted).

**B-D15 (decision).** Next, in order:

1. Ask the supervisor for questions where a graph should help (across wells and reports, counts, comparisons), or for the expert question set, since the 31 development questions are mostly single-fact lookups that plain RAG already answers.
2. Filter retrieval by well or document using the ID payload (§5.11), to stop wrong values from distractor reports.
3. Run LightRAG (B-D10 step 3) with Qwen3-8B on the three-report pool, and compare with the fusion baseline (26/31).
4. Try the library's own retrievers (vector-Cypher, Text2Cypher) only if step 1 brings questions that need them.

## 2026-10-31 (night): well routing

**B-C11 (design choice).** Retrieval can be routed by the well a question names.

- Every retriever takes an `allowed` chunk set, applied before ranking, as a vector-store payload filter would be.
- `WellRouter` (`wells:<retriever>`) finds well names in the question (`AK-3`, `TG-2`, `56-32`; casing sizes like `4-1/2` are skipped) and allows only the documents that name one of them. A question with no known well is not filtered.
- Each document's well names stand in for the "well registry IDs" of the §5.11 payload until Track C's registry exists; the router then reads the payload instead.
- BM25 computes its term statistics over the allowed chunks, as a separate index per well would.

**E18 (experiment).** Well routing: [E18](../../experiments/E18-well-routing.md).

- Three reports, BM25: hit@5 0.78 unfiltered, 0.91 routed with shared statistics, **1.00** routed with filtered statistics (equal to AK-3 alone).
- Answers with Qwen3-8B: **28/31** routed, against 26/31 for unrouted fusion; routed fusion stays at 26/31.
- No added calls or tokens.

**B-F21 (finding; from E18).** A filter must also scope the term statistics. Filtering a shared BM25 index after scoring under-weights terms that are rare in the target report but common in the others (hit@5 0.91 instead of 1.00).

**B-D16 (decision; from E18).** The multi-report baseline is BM25 routed by well, Qwen3-8B, top 5: 28/31 on three reports. It replaces fusion as the multi-report retriever in B-D12; fusion is kept for questions that name no well.

- *Why:* E18. Routing costs nothing and recovers the one-report result.
- Consequence: on questions that name one well, plain RAG is not hurt by more reports. A graph must be judged on questions that name no well, several wells, or ask across reports (B-D15 step 1).

## 2026-10-31 (late night): LightRAG set-up, a probe across reports, K2 version 1

**B-C12 (design choice).** Answer prompts label passages by chunk number (`[c0005]`) only when all passages come from one report; mixed reports get full chunk IDs, because every report has a `c0005`. Single-report prompts are unchanged, so E14 to E18 results and the request cache stay valid. `baseline.py` gained `--questions` (question set), `--answer-format` and `--fresh` (bypass the cache, to re-measure under new server settings).

**B-C13 (design choice).** `graphrag/lightrag_run.py` runs LightRAG 1.5.7 (HKUDS, MIT, used as a library, in its own `.venv-lightrag`).

- Our K1 chunks go in through `ainsert_custom_chunks`; LightRAG's chunk IDs hash (document, text), so its retrieved chunks map back to K1 IDs by text (0 unmapped in every run).
- LightRAG calls our model client, so its calls are cached and land in the cost ledger; one request at a time (B-C10).
- Retrieval uses `aquery_data`; its entities, relations and chunks then go through the baseline's answer prompt, citation check and scoring, so only retrieval differs.
- The Qwen3-8B server runs with `-c 32768 -np 1` for E19, because LightRAG's extraction prompts and its default 30,000-token query context do not fit an 8k slot. The baseline re-measured under `-np 1` with `--fresh` gives the same 28/31 (AK-3 and three reports), so the server change is not a confound.

**B-C14 (design choice).** A cross-report probe of 9 questions, `graphrag/gold/cross_report_probe.json`: comparisons, a count, people shared across reports, planned against actual, a relation between wells. Gold values and chunk IDs come from the three reports' text.

- It is a development probe, not an evaluation set (D-49); the expert question set replaces it. It also serves as examples of graph-worthy questions for the supervisor (B-D15 step 1).
- Result rows now record `gold_facts_retrieved`: how many of a question's facts have a passage among the retrieved ones. "Gold chunk retrieved" counts any one, which overstates retrieval for questions across wells.

**B-F22 (finding).** The answer schema's field order makes the model abstain.

- Plain RAG answered 0/9 probe questions. For p08 ("injection in which well was 68-32 drilled to monitor?") the answer passage was ranked first, and Qwen3-8B still returned `not_stated`; with that passage alone, or with two passages, it answered 58-32.
- Constrained decoding writes fields in schema order, and `status` comes first: the model decides whether to answer before writing anything, and more context pushes it to abstain.
- An `evidence_first` format (a short evidence note, then answers, then status) answers p08 and p03 (2/9 on the probe) and leaves the 31 questions at 28/31 (q31 now right, q05 now wrong).

**B-D17 (decision).** K2 version 1, the thin ontology slice for end-of-well reports: [`configs/ontology/k2_eowr_v1.json`](../../../configs/ontology/k2_eowr_v1.json).

- 9 entity types, 13 relation types and 19 properties with units, each tied to the section headings where it appears, taken from the three reports' headings and table columns and the prototype's 14 properties (unchanged).
- 104 glossary entries generated in code (`python -m graphrag.ontology glossary`) from the abbreviation and unit tables, each with its source table. Four entries from merged cells are flagged for a person (`JSA jt`, `LGS LOT`).
- `python -m graphrag.ontology guidance` renders the slice as LightRAG's `entity_types_guidance`, the injection point for an ontology arm.
- *Why:* D-49 (thin, from the reports themselves) and B-D15 step 4. Not reviewed by a domain expert.

## 2026-11-01: LightRAG on three reports, and per-well facts

**E19 (experiment).** LightRAG against the baseline: [E19](../../experiments/E19-lightrag.md).

- 31 single-well questions: LightRAG `mix` 25/31 on AK-3 and on three reports (small or default budget), `naive` 22 to 25/31, `local` 21/31; the baseline stays at 28/31.
- Indexing: 13,600 to 15,300 tokens and about 22 s per page; a keyword call and 1.6 to 6 times the baseline's prompt tokens per question.
- Probe: plain RAG and LightRAG each reach 3/9, on different questions; 6 distinct questions are answered by one or the other.

**B-F23 (finding; from E19).** LightRAG's graph helps on different questions, not on more of them. It links a person across reports (p05, Mary Mann) and gathers one value from every well (p02), which passages alone do not; it loses p06 and confuses TG-2 with TG-4 (q03). More graph context (the default 30,000-token budget) answers fewer probe questions than the small budget.

**E20 (experiment).** Per-well facts as answer context: [E20](../../experiments/E20-well-fact-sheet.md).

- neo4j-graphrag with Qwen3-4B on three reports: 2.5 calls and 4,750 prompt tokens per page; AK-3 recall 0.56 (E16 on AK-3 alone: 0.85), 47% right where keyed. 364 of 737 facts are about 68-32, many junk from daily-report tables.
- Adding each named well's facts before the passages: 28/31 to **21/31**, and 3/9 to **1/9** on the probe.

**B-F24 (finding; from E20).** Unvalidated extracted facts make answers worse; contradictory values (three rig-release dates for AK-3) pull the model off the right passage. Facts must pass validation (§6.2 stage 6) before they reach the answer model.

**B-D18 (decision; from E19 and E20).**

1. **LightRAG is not adopted as the base on this evidence.** The D-50 baseline stays: plain RAG, Qwen3-8B, BM25 routed by well.
2. Graph value is to be shown on questions across wells and reports. The probe (B-C14) and the supervisor request ([ask-supervisor-graph-questions.md](ask-supervisor-graph-questions.md)) serve that.
3. Next: LightRAG with K2 injected (E21), to see whether our ontology makes its graph precise enough; then a validation step for extracted facts (verbatim value in the cited chunk, unit, one well name per registry entry) before any graph fact reaches an answer.

**B-C15 (design choice).** `graphrag/validate.py` checks extracted facts before they reach an answer (§6.2 stage 6, B-F24): the value is written in its source chunk; the well name resolves to one well that its own document names; zeros (empty daily-report form fields) are dropped; per well, property, qualifier and context the best-supported value wins and a tie drops the key. Each rejection is counted by reason. `baseline.py --fact-sheet <graph> --validate` uses it.

**B-F25 (finding; from E20).** Validated per-well facts help on questions across wells without hurting single-well questions.

- Validation keeps 96 of 737 facts (146 values not in their chunk, 134 zeros, 128 without one well name, 127 contradicted, 28 with a well foreign to their document).
- With the validated sheet: 28/31 on the single-well questions (raw sheet 21/31) and **5/9 on the probe** (no sheet 3/9, raw sheet 1/9; LightRAG 3/9).
- Caveats: one run, 9 team-written probe questions, an extractor with 0.56 AK-3 recall.

**B-D19 (decision; from E20).** The working design is plain RAG (D-50) plus a validated per-well fact graph, used for the wells a question names.

- The graph part is extraction (any base that keeps chunk provenance) followed by validation in code; nothing unvalidated reaches an answer.
- To confirm on the expert question set before it becomes the chosen base. Improve extraction recall next (K2 slice, table rows mapped deterministically), and add people and projects (p05) and document counts (p07), which the 14-property profile does not cover.

**B-F26 (finding; from E20).** neo4j-graphrag extraction with Qwen3-4B is not stable across server restarts, even with identical requests.

- AK-3 alone, library prompt, one request at a time: recall 0.561 under `-c 16384 -np 1` and again 0.561 under E16's `-c 32768 -np 4` on a fresh server (`--fresh`, no cache). E16 recorded 0.854 with the same 113,964 prompt tokens.
- Only decoding differs (11,360 against 11,269 completion tokens); most of the gap is one survey table (26 against 12 inclination facts). The E16 result file predates the concurrency flag, so its exact run conditions cannot be reconstructed.
- Consequence: a single extraction run is not a measurement. Report extraction recall as a range over runs, and never let extracted facts reach answers unvalidated (B-C15).

**B-F27 (finding; corrects B-F26).** Today's extraction runs are repeatable; E16's recall is the one that cannot be reproduced.

- A second fresh three-report extraction (`E20_graph_three_qwen3-4b_run2.json`) gave the same 737 facts and recall 0.561 as the first; AK-3 alone gave 0.561 under two server settings. Pooling the two runs before validation changes nothing.
- So "unstable across server restarts" in B-F26 is wrong. What stands: E16's 0.854, with identical prompts, is not reproduced by any run since, and the E16 file does not record its concurrency. Recall figures for this extractor should be taken as 0.56 until a run shows otherwise.

**B-C16 (design choice).** K2 carries deterministic table mappings (`table_mappings`), and `graphrag/tables.py` applies them with no model call: series tables (inclination, projected temperature, casing depth by size) and row tables (productive, non-productive and total rig time). Headers match as whole words; the well is the document's most-named well; "Planned" in the caption sets the qualifier; each fact cites the chunk holding its row.

**E22 (experiment).** Table facts: [E22](../../experiments/E22-table-facts.md).

- AK-3 fact recall: tables 0.68 with 0 calls; LLM 0.49; both 0.88 raw, 0.78 validated (116 facts).
- Answers with the validated sheet from both: **30/31** (only q05 wrong) and 4/9 on the probe. Table facts alone: 26/31 and 2/9.

**B-F28 (finding; from E22).** Table rows and prose need different extractors: tables give the series (inclination, casing, rig time) for free and exactly; the LLM gives well-level values written in prose (total depth, dates). Neither alone matches the two together.

**B-D20 (decision; from E22).** The fact graph of B-D19 is built from two sources, both validated: K2 table mappings (no model call) and LLM extraction for prose. Next: check the mappings on reports they were not written from (daily reports, new end-of-well reports), and extend K2 mappings with Track A's table output (K1 version 1).

**B-C17 (design choice).** Table mappings find header rows from content (leading rows where under a quarter of the cells are bare numbers) and accept only short headers (at most 50 characters), because the parser's header counts are wrong on 56-32 and 68-32's daily-report forms come out as grids of paragraphs. The fact sheet can be ranked: `--sheet-properties N` shows only the facts of the N K2 properties whose definitions best match the question (Qwen3-Embedding-0.6B). K2 gained `spud_to_release_days` and `total_rig_time` from the prototype profile, and `scoring.normalize` reads `09-Mar-19`.

**B-F29 (finding; from E20 and E22).** The cross-report probe cannot separate setups: across six fact-sheet variants it scored 1, 2, 2, 3, 4 and 5 of 9, and single answers flip with context alone (adding 56-32's survey lines flipped p03 and p04). The single-well result is stable: 30/31 with three different validated sheets. A judgement on graph value across wells needs the expert question set or a larger probe.

**B-C18 (design choice).** K4 version 0.1, the answer record Track B publishes for Track C (§4.5): [`schemas/k4_answer_record.schema.json`](../../../schemas/k4_answer_record.schema.json).

- One JSON line per question: question ID and text, status, normalized answer values with units, citations as child chunk IDs with how each was checked (B-C08), the pipeline (base, retriever, *k*, fact sheet, validation, answer format), the answer model, and the answer call's calls, tokens, seconds and cost; `correct` when the question set has gold.
- `python -m graphrag.k4 <run>` writes `graphrag/results/<run>.k4.jsonl` from any answer run. The first file is from the working design's E22 run (31 records, valid against the schema).
- Chunk IDs are K1 version 0 IDs until Track C's §5.11 IDs replace them. Index-time cost stays in the run's result file and experiment record.

**E21 (experiment).** LightRAG with K2 injected: [E21](../../experiments/E21-lightrag-k2.md).

- K2 rendered as `entity_types_guidance`: 925 entities and 1,385 relations (defaults: 2,114 and 3,099), typed well, hole section, formation, project, person, rig; 225 untyped. Same extraction cost (15,900 tokens per page).
- Answers: 26/31 (defaults 25/31); probe 3/9 (small budget) and 4/9 (default budget, including p07, the report count, for the first time).

**B-D21 (decision; from E19 to E22).** Close the base comparison for this stint.

1. **No GraphRAG base is adopted wholesale.** The working design (B-D19, B-D20) is plain RAG routed by well, plus a per-well fact graph from K2 table mappings and LLM extraction (neo4j-graphrag as the extractor), validated in code: 30/31 on the development questions.
2. **LightRAG with K2** is kept as the candidate for document, project and people structure (p05, p07), to be tested again when expert questions ask for it.
3. The open decision moves to the supervisor: graph-worthy questions (30 or more) are needed to judge the graph's value across wells (B-F29). Until they arrive, Track B works on what does not depend on them: fact-graph coverage of people, projects and documents, and running on Track A's K1 version 1.

## 2026-11-04: simulated expert questions

**B-D22 (decision; narrows D-49).** The supervisor asked the team to wait for the expert questions, so Track B uses a simulated set until they arrive: [`graphrag/gold/simulated_expert_v0.json`](../../../graphrag/gold/simulated_expert_v0.json).

- *Who wrote it:* Claude, at Tri's request. No drilling expert has reviewed it, so results must always be reported as "simulated set", never as expert validation.
- *Contents:* 40 questions on the three end-of-well reports.

  | Kind | Count |
  |---|---:|
  | Single-fact lookups in prose or tables | 22 |
  | Daily reports (from the 68-32 appendices) | 4 |
  | Comparison, cross-report, multi-hop, count | 8 |
  | A depth stated two ways in one report | 1 |
  | Must not answer (not stated, off-topic, injection) | 5 |

- *Frozen before any run:* a result never changes a question or gold value; changes go into a new version.
- *Checked:* a test confirms each non-derived gold value is written in its cited chunk. The "not stated" questions were checked by search: 68-32 cost fields are empty, and H2S appears in 56-32 only as an abbreviation.
- *Limits:* it comes from the same reports as the table mappings, so it does not test them on unseen reports. It is also larger than the probe but still small, so differences of a question or two are noise.
- *Why:* the graph's value and the pipeline's general quality cannot be judged on the 31 lookups (B-F29).

**E23 (experiment).** Working design against plain RAG on the simulated set: [E23](../../experiments/E23-simulated-set.md). Results are on the simulated set, not expert-validated.

| | Plain | Design | Plain, per well | Design, per well |
|---|---:|---:|---:|---:|
| Correct of 40 | 29 | 29 | 31 | 30 |
| Wrong values given | 0 | 1 | 5 | 5 |
| Prompt tokens per question, median | 1,438 | 1,580 | 3,117 | 3,407 |

**B-F30 (finding; from E23).** The fact graph does not improve answers on the simulated set: the top-5 setups tie with the same 11 misses, and the per-well setups differ by one question. E22's gain on the 31 questions does not carry over. Building the graph costs 2.48 LLM calls per page.

**B-F31 (finding; from E23).** The sheet rarely holds what is asked: 4 of 35 gold values are in it on a gold chunk. K2's facts have no rigs, people, companies, rotary Kelly bushing heights or casing grades. This supports the coverage work in B-D21, but it does not show that coverage would help.

**B-F32 (finding; from E23).** `validate.py` passes facts with the wrong meaning, because it checks only that the value is in the chunk. All 13 of 68-32's kept `casing_depth` facts come from the LLM, none gives the true 978 ft, and their casing sizes include `10031` (the rig number) and `1-39` (a time code). s33's wrong answer comes from such a fact and from AK-3's planned depth. B-C15's checks need to cover the context and the qualifier.

**B-F33 (finding; from E23).** Per-well fusion with evidence first trades errors: cross-report questions go from 0/3 to 2/3, wrong values from 0 to 5, prompt tokens up about 2.3 times. Using it only for questions naming several wells would give 31/40 with 1 wrong (plain) and 32/40 with 0 wrong (design). Those two figures are computed from existing rows, with the rule chosen after seeing them, and need a real run on new questions.

**B-F34 (finding; from E23).** Two flaws in how the simulated set is measured.

- s02's gold (1.75°, from prose) conflicts with the report's survey table, which ends at 2° at 1,900 ft. The set stays frozen; fix it in the next version.
- `gold_facts_retrieved` counts a fact as found when any one of its chunks is retrieved, so it overstates retrieval on comparison questions.

**Open, for Tri (recommendation from E23).** No decision changes yet: D-50 stays the baseline, and the working design is neither confirmed nor dropped. Recommended order:

1. Route by the number of wells named, and test it on new questions.
2. Tighten the validator (B-F32).
3. Add coverage to the fact graph only after those two, since coverage alone would feed more unchecked facts to the model.

**B-C19 (design choice).** E24's gold names PDF pages, not chunks, and was written from the rendered pages before the attachments were parsed, so it does not inherit parsing errors. `data.chunks_on_pages` maps pages to whatever chunks a parser produces. `graphrag/oracle.py` answers with retrieval bypassed, giving the model the gold value's source page, to separate parsing, retrieval and model failures. It reads the gold data, so it is a diagnostic only.

**E24 (experiment).** Plain RAG on the AK-3 daily reports: [E24](../../experiments/E24-ak3-daily-reports.md). Simulated questions, not expert-validated.

| Setup | Correct of 30 | Wrong values |
|---|---:|---:|
| Plain: BM25 routed by well, top 5 | 5 | 2 |
| Fusion, top 10, evidence first | 9 | 13 |
| Right page given, status first | 11 | 1 |
| Right page given, evidence first | 19 | 4 |

**B-F35 (finding; from E24).** On daily reports, retrieval and the answer format lose the most. Filtering by well does not separate days, questions write dates differently from the forms, and 630 of 898 chunks have no date in their text or section. 5/30 rises to 19/30 with the right page and evidence first. Confirms B-F22 on forms (11/30 status first, 19/30 evidence first on the same pages).

**B-F36 (finding; from E24).** Parsing sets the ceiling on daily reports: 9 of the 27 gold questions fail even with the right page, because form headers are read in the wrong order, form regions lose their table structure, and some printed values are missing. Operations, mud and survey tables work (6/6 with the right page). The list for Hung is in the record. K1 version 1 needs key-value pairs from form headers and a report date on every chunk.

**B-F37 (finding; from E24).** Corpus pipeline problems for its owners: `process --workers 2` hung after exactly 40 documents in two runs (`max_tasks_per_child=20`; the cause is inferred, not traced); `scripts/run_ak3_appendices.py` prints "done" after every document fails and does not retry failed ones; `appx-04` now fails validation, though E8 processed it on an earlier commit.

**B-F38 (finding; from E24).** One answer changed between the first run and the uncached repeat with one request at a time (d20, from a wrong `1955` to an abstention; the score stayed 5/30). B-F19's rule is necessary, but it does not guarantee identical answers here.

**B-C20 (design choice).** The request to Track A is written as a file: [note-for-track-A-daily-reports.md](note-for-track-A-daily-reports.md).

**E25 (experiment).** Table mappings on an unseen report, 78-32: [E25](../../experiments/E25-table-mappings-unseen-report.md). As written: 3 facts, right depths, 2 with the wrong size, and a 20-row survey missed. After two general fixes: 23 correct facts, no change on the original three reports.

**B-F39 (finding; from E25).** E22's caveat was real: written from AK-3, the mappings got most keys wrong or missed the table on an unseen report. One unseen report from the same project is one sample.

**B-C21 (design choice).** Routing and strict facts, both opt-in flags so earlier runs stay reproducible. `--multi-well-retriever`: questions naming several wells use per-well fusion, top 10, evidence first. `--strict-facts`: a casing size must look like one and be in the fact's chunk, the value must differ from it, a depth context must be in the chunk, and planned facts are hidden unless the question asks about a plan. K4 records now give the pipeline each question actually used.

**E26 (experiment).** Routing and strict facts on 36 new questions, simulated: [E26](../../experiments/E26-routing-and-strict-facts.md). Top 5: 20. Always per well: 23. **Routed: 23, with 30% fewer prompt tokens.** Fact sheet, routed: 21; with strict facts: 23.

**B-F40 (finding; from E26).** Comparison questions are unsolved: 0/5 in every setup. The model abstains, returns the numbers instead of the well, or picks the wrong well. Comparing values in code is the candidate; it has not been tried.

**B-F41 (finding; from E26).** `WELL_NAME` does not match a well name followed by a period ("Well 68-32."), so such a mention is not routed. Not fixed, because a fix could change baseline results; it should be tested on its own.

**B-C22 (design choice).** `dates:<retriever>` filters by the report date a question names. `page_dates` reads `Report For`, then the date another attachment gives the page's `Report No`, then the previous page's date. 143 of 145 pages are right against the PDFs' text. A stand-in until K1 version 1 carries report dates.

**E27 (experiment).** Date filter and added coverage: [E27](../../experiments/E27-date-filter-and-coverage.md). Daily reports, 26 unseen simulated questions: 7 without the filter, **14 with it (wrong values 3 to 2)**, 17 with top 10 and evidence first (6 wrong). K2 version 1.1 added 24 facts with no model call and changed nothing measurable.

**B-F42 (finding; from E27; corrects a sentence in E24).** E24's right-page diagnostic is not an upper limit for better retrieval: 21/30 exceeds its 19/30, because the filter shows several attachments' copies of a day and one copy may parse better than another.

**B-D23 (decision, by Claude, delegated by Tri on 4 November).** The baseline for this stint, replacing D-50's retrieval settings:

| Reports | Questions | Setting |
|---|---|---|
| End-of-well | Naming one well, or none | BM25 routed by well, top 5, status first |
| End-of-well | Naming several wells | Per-well fusion, top 10, evidence first |
| Daily | Naming a date | The same, with the date filter |

- *Why routing:* same score as always per well at 30% fewer tokens, 3 more right than top 5.
- *Why status first on daily reports:* evidence first gains 3 of 26 but gives 3 times the wrong values, and a wrong number is worse than "not stated".
- *Cost accepted:* routing raises wrong values on held-out questions from 5 to 7.
- *Revisit when* the expert questions arrive, or K1 version 1 changes what forms look like.

**B-D24 (decision, by Claude, delegated by Tri on 4 November; replaces B-D19 to B-D21's working design).** The fact graph leaves the baseline and stays as an option.

- *Why:* on questions written after it was designed, it does not beat plain RAG (E23: 29 and 29; E26: 23 and 23; E27: 23 and 23), and it costs 2.48 LLM calls per page. Its gain appears only on the prototype's questions, which shaped it. Efficiency is a headline metric, so it must earn that cost.
- *Kept:* the code, `--strict-facts`, and table mappings, which cost no model calls.
- *Stopped:* further LLM extraction and more coverage.
- *Limit:* this is a capstone GraphRAG application, and the supervisor's direction expects a graph. This decision is about the answer pipeline on the questions we have, all simulated. It is not a verdict on graphs across wells, and **the expert question set decides it for good.** Tell the supervisor at the next check-in.

**Track B has no run waiting.** What comes next depends on others: [next-runs.md](next-runs.md).


## 2026-11-04: papers from the supervisor

The PDFs are not kept in the repository, because of their copyright terms.

**B-F43 (finding).** Queiroz et al., "An Ontology of Well Engineering Entities to Extract and Structure Text Data from Daily Reports", SPE/IADC-223801-MS, 2025 (Petrobras, UNESP, Unicamp). DOI 10.2118/223801-MS.

- *What it builds:* a knowledge graph of **events**, not of per-well properties. Each operational log entry becomes an Activity linked to the components, fluids and properties observed in it. `Observed{Class}` nodes let one entity have different values at different times.
- *How it extracts:* regular expressions per class (stored in the ontology), part-of-speech tagging checked against a lookup table for activities, and relationship heuristics. They chose regex over Transformer models for accuracy. LLMs only propose candidates for humans to review, and LLM extraction is future work.
- *How it evaluates:* Competency Questions written first, for example incident counts per intervention, trip time rates, and well status at a given moment. They are answered with SPARQL.
- *Limits:* it gives no numbers, only "high levels of recall and precision" and "improved" against raw text. It does not compare answer quality with plain RAG, so it neither supports nor contradicts B-D24. About 2,300 classes, from 129 wells and about 145,000 log entries, took experts several months. Reports are in Portuguese, and the paper gives no link to the ontology.

**B-F44 (finding).** Maucec and Khawaja, "Knowledge Graph-based Petroleum Engineering Ontological Framework for Well Performance Assessment", 87th EAGE Annual Conference (Saudi Aramco). An OWL ontology with SWRL rules and a reasoner, classifying 300+ wells from a performance study into 6 classes. Reservoir side only: it names drilling as out of scope. No documents, retrieval or LLM, and no accuracy figures. One idea applies: derived values are computed at query time by rules, not stored.

**B-F45 (finding; our reading of B-F43 against E23 to E27).** Our fact graph may have been tested on the wrong shape of graph and question: per-well static properties against mostly single-fact lookups, which retrieval already answers. The paper's graph targets counts, rates and states across many log entries, which retrieval cannot assemble. Our operations tables are the part of daily reports that parses well (E24). Not tested yet. A proposed test: events from operations-table rows with no model call, and competency questions frozen first (hours by activity code, non-productive time, depth on a date).

**B-D25 (decision; from the supervisor, relayed by Tri, 4 November).** No ontology work for now: the direction is GraphRAG. The papers in B-F43 and B-F44 are background only. Their ontology methods (OWL, Protégé, reasoners, large class hierarchies, upper-ontology alignment) are not to be adopted, and D-49's thin K2 stays as it is. B-F45's event idea, if tried, must be a thin graph for GraphRAG answers, with no new ontology.

**Open, for Tri and the supervisor.** "GraphRAG for now" sits uneasily with B-D24, which takes the fact graph out of the baseline. B-D24 stands on the numbers until the supervisor has seen them; he may prefer a graph in the main pipeline regardless.

**B-F46 (finding; corrects a reading in the session of B-F43).** The supervisor sent the two papers before his GraphRAG direction, so they do not signal what he expects now. B-D25 stands: they are background.

**B-C23 (design choice; documents brought up to date).** The sources of truth now state what runs today.

- *Added:* specification §8.4 (what the first build runs today, with the architecture diagram) and version 3.2, D-52, and an architecture section in `graphrag/README.md`.
- *Removed as superseded:* "working design" as the current design, in the specification's §9, the plan and `CLAUDE.md`; "LightRAG with K2 next"; "the team writes no question set of its own"; the `-np 4` server command and the separate multi-report command in `graphrag/README.md`, replaced by `-np 1` and "The baseline".
- *Kept:* specification §8.1 to §8.3 as the GraphRAG target, because the direction has not changed.

## 2026-11-05: the event graph

**B-C24 (design choice).** `graphrag/events.py`: well → report date → event → activity code and non-productive code, built with no model call from operations tables merged across attachments and joined with appx-23 by date and time. The model writes a JSON plan, code runs it, and the model writes the answer from the result and the source passages. Kept in memory, not in Neo4j; no new ontology (B-D25). K4 gains `how: event_graph` for chunks holding the source events of a computed result. `page_dates` is fixed: 145 of 145 pages.

**E28 (experiment).** Event graph on questions over time: [E28](../../experiments/E28-event-graph.md). Simulated questions, chosen to suit it. 161 of 161 events match the PDFs' text layer. Frozen 35: **22** against 5 at best for plain RAG. New 23, after a planner fix: **19** against 4. 26 daily lookups: 17 against 14.

**B-F47 (finding; from E28, answers B-F45).** The shape of the graph has to match the questions. Static per-well facts duplicate what retrieval finds; events add what it cannot do, because plain RAG sees five to ten passages and cannot add up 27 days.

**B-F48 (finding; from E28).** The final model step garbles right results: on the new 23, the graph's result held the gold value on 19 of 20, and 16 were answered correctly (g07: result 6.5, answer 4). Reporting the result in code would give 22/23, computed and not run.

**B-F49 (finding; from E28).** No single daily-report source is complete. Summaries omit rows ("1 record not printed"), each attachment loses some, and the parser loses `X` marks and turned a one-row table into text. Merging them and joining appx-23 recovers all 161 rows.

**B-D26 (decision, by Claude, delegated by Tri; revises B-D24 for this kind of question).** Questions over time on daily reports are answered from the event graph, and other questions fall back to retrieval. This is D-53.

- *Why:* a wide margin on two question sets, no LLM call to build, and no harm to lookups. It also fits the supervisor's GraphRAG direction.
- *Cost accepted:* 2 LLM calls per question and about 900 more prompt tokens.
- *Limit:* the questions were chosen to suit it, and it covers one well and one report system. **Whether users ask such questions is for the supervisor and the expert set.** B-D24 stands for the per-well fact graph.

**E29 (experiment).** Table mappings across reports from other authors: [E29](../../experiments/E29-table-mappings-across-reports.md). Fixes from one report, tested on the others. Held-out casing strings: 4/16 as written, 14/16 after fixes (1 wrong fact), **13/16 after validation (0 wrong facts)**. Survey rows on the held-out report: 81 of 198 after validation, 7 wrong.

**B-F50 (finding; from E29).** As written, the mappings found nothing outside GRG's layout, though they stated nothing false. The causes were general: well names with several parts, an `Item` column, Unicode fractions, and a depth column named `MD`.

**B-F51 (finding; from E29).** Metre depths would have been labelled as feet. Facts now carry `unit`, and metre surveys use `depth_m`.

**B-F52 (finding; from E29).** The strict validator (B-C21) discarded right facts, because it looked for `13-3/8` in text saying `13 ⅜"`. The raw score looked good while almost nothing reached the model. Table results must be scored after validation as well.

**B-F53 (finding; from E29).** Surveys from these reports are not reliable: half the rows at best, and 8% of validated rows wrong on the held-out report, because the parser merges dense tables. Scanned reports are out of reach: Raft River comes out column by column. Both are for Track A.

**B-F54 (finding; from E29).** There is still no evidence on a different author's modern digital report. Three of the five held-out reports share a consultant with the dev report, and the one different author is a scanned 1976 report, which fails.

**B-C25 (design choice).** `graphrag/table_eval.py` scores table facts against independent gold, raw and after strict validation. K2 version 1.2: `casing_items`, `number_cells`, `max_step`, and `depth|md`. `WELL_NAME` reads names with several parts (`TNT-GT-01`, `HON-GT-01-S2`). Well names on the original three reports are unchanged, and those reports lose only 4 junk facts.

**B-C26 (design choice).** Tri's status update for the supervisor is kept in the repository: [STINT_UPDATE_2026-11-05.md](../../reports/stints/STINT_UPDATE_2026-11-05.md) (moved to the stint reports folder on 24 November). It reports E23 to E29, the limits, and that all questions are AI-written. It asks for a specification to write development questions from, and raises whether users ask questions over time.

**Stint closed on 5 November.** No Track B run is waiting. Next steps depend on the supervisor's reply, Track A's K1 version 1 and Track C's stores ([next-runs.md](next-runs.md)). On our side, when work resumes: let code report the event graph's result directly, try the event graph on 58-32's daily reports, and try a different author's modern report.


**B-D27 (decision, by the team; told to Claude by Tri).** The owners of Tracks A and C swap from 5 November: Track A (ingestion and tables, K1) is now Khai's, and Track C (storage, IDs, end-to-end run) is now Hung's. Track B stays with Tri. The requests to Track A, including K1 version 1 and [the note](note-for-track-A-daily-reports.md), go to Khai; choosing the vector store and loading Neo4j go with Hung. Removed: the old owner names in `CLAUDE.md`, the plan, [next-runs.md](next-runs.md), E24's Track A heading and the note's title. Earlier dated log entries (B-F36) keep the name used at the time, and the meeting records are unchanged.

**B-C27 (design choice).** Tracks A and C now carry Track B's findings. The plan's sections for both gain a "What Track B found" block, with work, exit and starting points to match. [The note to Track A](note-for-track-A-daily-reports.md) gains end-of-well findings, the K1 fields Track B's code reads, and limits. [A new note to Track C](note-for-track-C-storage.md) covers what runs today, what the stores need, and which code depends on today's IDs. Removed from the plan's Track C: choosing the vector store by "the chosen GraphRAG base", the research question on candidate pipelines' storage (no base was adopted, B-D21), and writing a K4 schema (version 0.1 exists, B-C18). These state Track B's view only; each owner can change their own plan.

## 2026-11-09: Track A's K1 version 1 candidate

Khai pushed Track A's work to the branch `track-a-k1-package` (14 commits, 81 files): the K1 version 1 candidate ([E30](../../experiments/E30-k1-version-1-candidate.md)), Operations Summary tables rebuilt from the PDF text layer, quality checks and a table-extraction benchmark. Tri had Claude review it and merge it into `main`: no conflicts, 614 tests pass (11 skipped).

**B-C28 (design choice; from E30).** `graphrag` reads both chunk ID formats: K1 version 0 (`<doc_id>#c0005`) and Track A's version 1 candidate (`f<hex>:s6:c0`, no `#`). `graphrag.data` gains `document_key`, `short_id` and `cited_id`, which replace the four places E30 found splitting on `#` (`citations.py`, `baseline.py`, `validate.py` twice). Version 0 runs give the same IDs as before: a short label in a pool of several reports still means `<default report>#<label>`. `scripts/check_k1_graphrag_compat.py` now reports no gaps, and its test says so.

**B-C29 (design choice; from E30).** K2's `sources` name K1 version 0 table IDs. Table mappings do not use them: they match tables by their headers, so they run on a K1 version 1 package as they are. Only `python -m graphrag.ontology glossary` reads them; it now also matches a table's `logical_id`, where K1 version 1 keeps the version 0 ID. That holds only while a new run numbers tables as the old bundle did, so check the glossary after regenerating it from a new package. Regenerating it from `data/processed/gdr_tables.jsonl` gives the same 104 entries. K2 itself is unchanged.

**B-F55 (finding; from reviewing E30).** Three things in E30 are not settled by code:

1. **Retrieval drops on the new chunks:** BM25 hit@5 on the prototype questions is 0.913 with `rapidocr`, against 1.000 on the old bundle (Khai's measurement). q03's gold chunk was cut differently, and on q11 a new chunk made by OCR of a figure outranks the gold chunks. Answers were not run. Track B reruns E17's baseline on the package once it is shared.
2. **The package is not in the repository.** E30 links a committed sample in `data/processed/k1/ak3-k1-candidate/`, but no file there is tracked, so the numbers above cannot be rerun here yet.
3. **The ID scheme.** The plan gives the §5.11 ID scheme to Track C, and Hung's log says it is to be agreed with Track B first. E30's IDs (`<file_id>:s<n>:c<n>`, tables `<file_id>:t<n>`) and six `k1_*` schemas are Track A's proposal. They sit next to Hung's `k1_chunk.v0` without conflict. Track B's code now reads either format, so Track B can accept either; Hung decides.

**B-D28 (decision, by Tri; answers B-F55 item 3). This is D-54.** Chunk and table IDs follow specification §5.11 in the format Track A's K1 version 1 writes (E30): `f<first 16 hex of the PDF's SHA-256>` for the file, then `:p<n>` page, `:t<n>` table, `:s<n>` section parent, `:f<n>` form parent, and `<parent>:c<n>` child chunk.

- *Why:* it is already the format of §5.11, and it is built and tested. The file part is a hash of the PDF bytes, so an ID does not change when a document is renamed, and a rechunk changes only the child part. Version 0's `<doc_id>#c<nnnn>` numbers chunks in order, so any rechunk renumbers them.
- *Cost accepted:* gold data written against version 0 IDs (`prototype/gold/ak3_facts.json`) goes through the old-to-new map, which E30 measured at 15 of 17 cited chunks with `rapidocr`. Version 0 runs keep their IDs.
- *Ownership:* Tri chose; who owns the scheme matters less than having one. Track C builds the stores and loader on it.
- *Retrieval:* a lower hit rate on the new chunks (B-F55 item 1) is expected after rechunking and is not a reason to change the IDs.

**B-D29 (decision, by Tri; reverses B-D24, which Claude made under delegation). This is D-55.** The per-well fact graph is part of the design, not optional. Tri did not decide to drop it.

- The system is GraphRAG with two graphs: the per-well fact graph for end-of-well reports and the event graph for daily reports (B-D26). Retrieval routed by well and date (B-D23) feeds both.
- Plain RAG is the baseline the graphs are measured against (D-50), not the system. Reports and documents describe it that way from now on.
- Validated facts go back into end-of-well answers (`--fact-sheet --strict-facts --sheet-properties 3`), and fact-graph work resumes: coverage, and loading into Neo4j with Track C.
- B-D24's measurements stand: on new lookup questions the fact graph ties retrieval (E23 29 and 29; E26 23 and 23) at 2.48 LLM calls per page. They show the lookup questions we have do not need it, not that the design should drop it. Questions across wells, which the expert set should bring, are where it is expected to help (B-F29).
- Removed: "optional" for the fact graph in `CLAUDE.md`, the plan, specification §8.4, Q3 and D-51 (marked replaced), `graphrag/README.md` and the note to Track C. Historical records (E28, E29, the old supervisor request) keep their wording.

**B-F56 (finding; answers B-F55 item 2).** The K1 package is not in the repository by design. Khai shared it with the team as a zip on 9 November, after Hung asked for it for the dry-run loader, and did not commit it because data pushed to git is hard to remove. The zip had not reached this machine when this was written. Two points to confirm with Khai: his message gives 1,042 chunks where E30 gives 1,040, and describes IDs as `docid:s1:c0` where E30 and the code write `<file_id>:s1:c0` with a file ID from the PDF hash (D-54).

**B-C30 (design choice; from B-F56).** Track B runs read a K1 package from outside the repository: `--pool k1_ak3` (the end-of-well report) and `--pool k1_daily` (the four daily-report attachments) load `data/interim/k1/chunks.jsonl`, or the file `GRAPHRAG_K1_CHUNKS` names, and stop with a clear message when it is missing. Gold chunk IDs of the prototype set are old IDs, so the retrieval hit flags in answer runs on these pools are not meaningful until they go through the legacy map; answer correctness is scored by value and is unaffected. E28's event graph still reads the old appendix tables and needs a K1 loader before it can run on the package.

**B-F57 (finding; from Track C's C-F04 and C-F05).** Hung loaded Khai's AK-3 package into Track C's PostgreSQL on his machine: 1,042 chunks, all 174 pages rebuilt from the database. His questions to Khai that matter for Track B:

- **No legacy ID map in the package.** Without `legacy_chunk_ids.json`, the prototype gold's old chunk IDs cannot be mapped, so retrieval hit rates on the package cannot be scored by chunk. Answer correctness is scored by value and is unaffected.
- **Which OCR engine.** E30's map covers 15 of the 17 cited chunks with `rapidocr` and 17 of 17 with `easyocr`, so the engine decides how much gold carries over.
- **End-of-well chunks have no well or date field.** Track B does not need one: `WellRouter` collects each document's well names from its own text, so well by file is enough, and only daily reports need a date. Track C can copy the file's well into the vector payload.

**B-D30 (decision, by Tri). This is D-56.** The vector store is pgvector inside the PostgreSQL that holds K1, as Hung proposed (Track C log C-D03, [comparison](../C-storage/vector-store.md)). It adds no service, filters by well and report date in the same query, and is rebuilt from the system of record. BM25 stays alongside it for one-well questions.

**B-D31 (decision, by Tri). This is D-57.** Khai's K1 version 1 proposal (E30) is the team's chunk-package interface, not only its ID format (D-54): the six `k1_*` schemas, forms as their own record, report date and well on daily-report chunks, and the QA sidecar next to each release. Packages are shared as files. Still asked of Khai: the legacy ID map with each package and the OCR engine used (B-F57).

**B-C31 (design choice).** The project report for the supervisors, 9 November, is kept in the repository as [docs/reports/PROJECT_REPORT_2026-11-09.md](../../reports/PROJECT_REPORT_2026-11-09.md), with Mermaid diagrams, in English. It describes the system as GraphRAG with two graphs (B-D29) and covers all three tracks, the roadmap and what the team needs from the supervisors. A web copy was shared from Claude; the file is the record.

## 2026-11-09: supervisor meeting

[Digest](../../requirements/supervisor-meeting-2026-11-09.md). Tri's microphone cut out for much of his part, so the transcript keeps little of his answers.

**B-D32 (decision, from the supervisor). This is D-58.** Keep a coordinator that routes each question to retrieval, the per-well fact graph or the event graph. The current routing (B-D23, B-D26, the event graph's fallback) is its first version. Later it treats these as tools among others, with MCP and connectors. How lanes are split or merged waits for the document scope and question types (Q13). Detecting the report type from the question, today chosen per run, is the next piece: the event graph's planner can return it in the same call.

**B-D33 (decision, from the supervisor). This is D-60 and D-62.** A simple UI on the connected tracks comes next, ahead of the rest of M2: question, answer, cited source text and retrieved passages, also showing the source events behind a computed total. And the model stays swappable: Qwen3-8B with thinking off is today's choice, not part of the design.

**B-D34 (decision, from the supervisor). This is D-61.** Reasoning about the causes of a drilling problem is a target question type. No question set covers it yet, and AK-3's reports alone likely cannot answer it. The supervisor also asked that node and relationship logic of both graphs be stated clearly; the per-well fact graph's LLM step today extracts only the 14 properties of `oil_wells.json`, not K2's relations.

## 2026-11-10: a simple UI

**B-C32 (design choice; from D-60).** `graphrag/ui.py` and `graphrag/ui.html`: a local UI over Track B's answers, standard library only, on 127.0.0.1.

- **Recorded runs:** any answer run in `graphrag/results/` with its questions, expected values, correctness, the path through the pipeline (lane, retrieval or graph, answer, citation check), the cited passage with its page, and tokens and time. For the event graph it shows the query plan and the events the total came from, by rerunning the recorded plan on the recorded graph (`E28_events.json`) with no model call: E28's TRPI question gives 8 events summing to 13 hours. A second run can be shown beside the first.
- **Live:** a new question goes through the same code as the runs. The lane is chosen from the question's words (dates, hours, NPT, activity codes mean daily reports), standing in for the coordinator of D-58. End-of-well questions use BM25 routed by well with the strict, validated fact sheet (12 lines per well, no property ranker, so no embedding server is needed); daily questions use the event graph's planner with its fallback. Hosted endpoints are refused, since the pools mix sources.
- `answer_questions` now also takes a list of questions with no gold; question sets work as before.
- Checked on the laptop: replay works for all 78 recorded runs, and live mode reports that no model server is running. A live answer was tested only with a stand-in model; it needs the desktop's llama.cpp.
- Not yet: reading chunks from Track C's PostgreSQL, the page image beside a citation, and answers on Khai's K1 package.

## 2026-11-10: the event graph on K1 version 1

Tri put Track A's package on the laptop: `ak3-k1-v1-candidate`, moved into ignored `data/interim/k1/`.

**B-F58 (finding; answers B-F57's questions from the package itself).** This package is E30's (1,040 chunks), not the 1,042-chunk one Track C loaded. It ships `legacy_chunk_ids.json` and its manifest names the OCR engine, `rapidocr`. Khai's compatibility check passes on it: every row loads, the four daily reports are found, all 191 tables give rows, the ID map covers 15 of the 17 gold chunks the prototype cites, and BM25 hit@5 is 0.913 against 1.00 on the old chunks, as E30 measured. `graphrag` reports no ID-format gaps.

**B-C33 (design choice).** `graphrag/events.py --k1` builds the event graph from the K1 package: daily-report chunks and tables from K1, each page's report date from the chunks' `context.report_date` instead of `page_dates`, and NPT codes joined from appx-23, which the package lacks, read from the corpus release or the older export (`npt_report_inputs`). `build_events` takes the dates as an optional argument; built from the corpus, nothing changes. `k1_chunks_path` also finds a package unzipped into its own folder under `data/interim/k1/`.

**E31 (experiment).** The event graph on K1: [E31](../../experiments/E31-event-graph-on-k1.md). 161 / 161 events identical to E28 in every field, 160 now linked to K1 chunk IDs, and E28's final recorded plans replay 35 / 35 and 23 / 23. No model call. The answer reruns need the desktop.

**B-D35 (decision, by Tri; a request to Track C).** Stop passing data between machines through chat. Track C (Hung) hosts the shared stores (PostgreSQL with pgvector, Neo4j, and a file store for K1 packages) on a free cloud tier, such as AWS or Azure through the GitHub Student Developer Pack, with credentials for each teammate, so all three tracks read and write the same data. High priority; Track C owns it, since it builds the database side, and adds Tri and Khai once the resources exist. Only public data goes there (AK-3, BSEE, GDR reports); private documents stay on local models and machines (specification §10, D-37). Credentials stay out of the repository.

### 12 November 2026

**B-C34 (design choice).** `graphrag/compare_runs.py` turns recorded answer runs into one side-by-side table per question set (gold, each method's answer and result, cost per method), as Markdown and CSV, with no model call. Written for anh Tuấn, who asked for the questions, both methods' answers and the benchmark method. Output: [E28-answers/](../../experiments/E28-answers/README.md); totals match E28 (22/35, 19/23 for the event graph).

## 2026-11-24: design of the second build

No experiment was run today. This is design and documentation, done with Tri, before any code.

**B-F59 (finding; state of the repository on 24 November).** Nothing from Track B or Track C is recorded after 12 November, and no supervisor contact after the 9 November meeting. Track A merged a large change on 17 November: table joining across pages, section context, form recognition, label-value repair, page orientation, quarantine and resumable runs, all as options that are off by default. The transcript Tri brought today is the 9 November meeting, already digested on 10 November; the digest matches it. Tri confirmed there is no newer direction to record.

**B-D36 (decision, by Tri; details D-58 and B-D32). This is D-64.** The coordinator is a router now, and an agent later in one lane only.

- One model call frames the question: its kind, the report type and, for a question over time, the event graph's query plan. This is the planner of B-C24 with two more fields.
- Code reads wells and dates as today, chooses lanes from a fixed table, and falls back to passages in a fixed order.
- Each lane (passages, well facts, events) gets the same input and returns the same evidence shape, so it can later be called as a tool or through MCP, which is what the supervisor described.
- A multi-step loop is considered only inside the reasoning lane, and only after a run shows a model of this size manages it.
- *Why:* a fixed router is cheap, repeatable and measurable; a free tool loop on an 8B model is unproven here and not needed for four of the five question kinds.
- *Test before adopting:* the 221 development questions in one pool with no lane given (31 + 40 + 36 + 30 + 26 + 35 + 23). Their source sets give the expected lane. The coordinator must match the hand-routed scores. It adds one model call to end-of-well lookups (1 to 2); event questions stay at 2.
- Not chosen: a tool-calling agent from the start, and rules with no model call.

**B-D37 (decision, by Tri; replaces the order in B-D33). This is D-65.** The application is built now as a FastAPI backend and a React frontend, read path first, instead of first pointing `graphrag/ui.py` at the stores.

- `graphrag` becomes the library the backend imports. `graphrag/ui.py` and `ui.html` stay as a developer tool for replaying recorded runs; they are not the product.
- Every question asked is logged with its lane, answer and any "wrong answer" mark. Shown to domain experts, that log is the route to real questions (Q2, Q13).
- Work is split by data, backend and frontend from this stint. Tri takes the frontend as well as the engine (his decision, 24 November). Khai on data and Hung on backend are the plan's proposal, for the team to agree (Q14).
- Not chosen: keeping the standard-library UI, and a thin FastAPI service that only serves today's HTML.

**B-D38 (decision, by Tri; details D-61 and B-D34). This is D-66.** The reasoning lane is designed and probed, not promised. It finds the problem event in the event graph, gathers what surrounds it in code (days before and after, the non-productive report's description, the day's passages, the end-of-well narrative), and answers in two parts: causes the reports state, and possible causes, each with a citation. About ten questions on AK-3's 28 non-productive events are frozen before any run and scored on two things: the stated cause found and cited, and no unsupported claim stated as fact. Nothing inferred is written to the graph. One well's reports hold no offset wells, formation pressures or lessons-learned reports, so the probe is meant to show the supervisor a concrete answer and what a useful one would need.

**B-C35 (design choice; answers the supervisor's request in B-D34). Proposed as D-67.** The node and relationship model is written down in [specification §8.5](../../PROJECT_DESIGN.md#85-the-graph-nodes-and-relationships): one graph with two regions joined at `Well` and `Chunk`.

- Event region, as Track C loaded it (C-C11): `Well`, `ReportDay`, `Event`, `ActivityCode`, `NptCode`, with `FROM` to `Chunk`.
- Fact region, proposed: `Fact` nodes (property, value, unit, qualifier, context, source) under `Well`, each with `FROM` to its chunk; `HoleSection` and `CasingString` from the casing mappings. These are the fields `graphrag/tables.py` already writes.
- `Document` nodes link a well's daily reports to its end-of-well report.
- A fact is a node, not a property on `Well`, because a well can have several values for one property, each with its own source.
- K2's other types (`Project`, `Organization`, `Person`, `Rig`, `Formation`) wait until a kind of question needs them (B-D25).
- To agree with Hung, who asked for it (Track C log, "Next").

**B-C36 (design choice; documents brought up to date).** What changed, and what was removed:

- Specification 3.4: §3 lists what the first build delivered; §4.1 has the coordinator and lanes; §4.2 states pgvector; §4.5 is marked closed; §4.6 is new (the second build); §7.5 separates the read path from administration; §8.1 to §8.3 are rewritten around the coordinator; §8.5 and §8.6 are new; D-64 to D-67 and Q14, Q15 are added.
- Removed from the specification: graph expansion by a fixed number of hops and community summaries (§8.1), which no run supported (E16, E19, E21); the vector-store candidates (§4.2), settled by D-56; the claim that the GraphRAG parts are not built (§3.1).
- Plan 3.2: rewritten. Removed: the M0 task list, the three tracks' research questions and work lists, the 30 October backlog and the note after the 9 November meeting. In their place: how M1 closed, the M2 checkpoints, and one task list by role.
- `CLAUDE.md`, the documentation index, the main README's status, and a new [tracks index](../README.md) with a pointer for Track A.
- Experiment numbers reserved: E32 answers on K1 version 1, E33 the coordinator on the pooled questions, E34 the reasoning probe.

## 2026-11-24: lanes, coordinator and the fact graph export

Code for plan tasks E3 to E6, written from the [implementation plan](plan-lanes-and-coordinator.md) on the laptop, with stand-in models. **No model was run and nothing was measured today**: the laptop has no GPU and no model files. E33 is the measurement, and it needs the desktop.

**B-C37 (design choice; builds B-D36).** `graphrag/lanes.py` puts the three answer paths behind one shape: `lane(question, frame, engine) -> Evidence`.

- `Evidence` has the lane's name, `exact` (true for facts and computed results, false for passages), `passages` (chunk IDs), `facts`, `computed` (plan, text, values, unit, events, source chunks), the answer format and the report type.
- `Engine` holds what the lanes read: the end-of-well chunks, the daily-report chunks, the events and the validated facts. Today it loads them from files (`Engine.load`); reading the stores replaces only that method.
- The settings are the baseline's (B-D23, B-D26), not new ones: `wells:bm25` top 5; several wells per-well fusion top 10 with evidence first; daily reports `dates:wells:bm25` top 5. No lane calls a model.
- The well-facts lane hides planned values unless the question asks about a plan (B-C21). Its passages are the chunks of the facts a prompt shows, 12 per named well, not of every fact: one well can have over a hundred survey facts.
- `graphrag/baseline.py` gains `answer_one`, the body of `answer_questions`' loop. The 40 requests of two baseline runs (the prototype's questions, and the probe with multi-well routing) are byte for byte what they were, checked by a test against hashes recorded from the code before the change, so the request cache and E14 to E31 still reproduce.

**B-C38 (design choice; builds B-D36).** `graphrag/coordinator.py`, the coordinator of specification §8.1.

- **Frame.** One call with `FRAME_SCHEMA`: `kind` and `report_type` first, then the event planner's fields (B-C24), so the plan is written knowing whether the question is one over time (the field-order lesson of B-F22). The system prompt is the planner's, plus one paragraph defining the six kinds and four report types.
- **What code decides.** A frame whose kind, report type or operation is outside its list is discarded for the empty frame, which routes to the end-of-well lanes. One well read in the question replaces the plan's well; two or more make the kind `across_wells`.
- **Route.** A question over time with a plan goes to `events`; a daily-report question to `passages`; anything else to `well_facts` then `passages`. `exact` mode drops `passages`.
- **Fallback.** If no routed lane finds anything, passages run: of the daily reports for a question over time or about them, else of the end-of-well reports.
- **Answer.** With facts and passages both found, the prompt is what E22 and E26 measured: the fact sheet before the passages lane's hits. Facts' chunks are not added to the passages.
- **Exact mode with nothing in the graphs:** status `not_found_in_graph`, no answer call, the closest passages returned as sources.
- `--no-embeddings` uses per-well BM25 for several wells, for a machine without the embedding server.

**B-C39 (design choice; this is task E6, and changes specification §8.1 and §8.3).** A result computed by code is the answer as code wrote it. There is no second model call for it.

- `graphrag.events.plan_value` returns a plan's result as values and a unit beside the text; `run_plan` wraps it and its text is unchanged, because Track C replays 58 recorded plans against that text.
- The answer row takes its values from code and cites the source events (`how: event_graph`).
- A computed answer now costs one model call (the frame), where E28 spent two. On E28's new set the two-call path scored 19 of 23, and E28 estimated from the rows that reporting in code would give 22; that estimate was computed, not run. E33 is to show what it gives.
- The specification said the model would word a sentence around the number. That is dropped: the result text is already a sentence, and one call fewer is cheaper.

**B-C40 (design choice; builds B-C35, D-67).** `graphrag/factgraph.py` writes the fact region as nodes and relationships for Track C's loader: `python -m graphrag.factgraph --facts <fact runs> --name <name>`.

- Nodes `{label, key, properties}`: `Well`, `Document`, `Chunk`, `Fact`, `CasingString`, `HoleSection`. Relationships `{type, from, to}`: `HAS_FACT`, `FROM`, `DESCRIBED_BY`, `HAS_CHUNK`, `HAS_CASING`, `HAS_SECTION`. Sorted and free of duplicates, so the same facts give the same file.
- Facts pass the strict checks of `graphrag/validate.py` first. A fact's `source` is `table_mapping` or `llm`.
- A casing string takes its depth, weight and grade from actual facts only.
- **Not written:** `CASED_WITH` between a hole section and its casing string, because no fact says which casing was set in which hole. Specification §8.5 now says `HAS_CASING` from the well instead.
- First export, [`E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json), from the two fact runs the current design uses (`E20_graph_three_qwen3-4b`, `E27_tables_three`): 892 facts read, 216 kept; 5 wells, 3 documents, 38 chunks, 11 casing strings, no hole section; no dangling relationship.

**B-F60 (finding; from the first export, B-C40).** Two things to check before the fact region is trusted:

- **Offset wells.** 13 facts are about TG-2 and TG-4, earlier Akutan wells that the AK-3 report describes. All 13 come from LLM extraction, and none is checked against gold. They are attached to the AK-3 report as their document, which is right, but a question about "the well" of that report must not pick them up.
- **A casing string that may be a hole size.** 68-32 has a casing string of size `8-3/4`, which reads like a bit size. Not checked against the report.

**B-C41 (design choice).** K4 version 0.2, written for coordinator runs only: `pipeline` gains `lanes`, `mode` and `frame_kind` with `base: "coordinator"`; `models` gains `frame`; `status` gains `not_found_in_graph`; `cost` adds the framing call to the answer call. Earlier runs still write version 0.1. Model roles (`frame`, `answer`, `extract`, `embed`) are in `configs/graphrag/roles.json` (D-62), read by `client.client_for`.

**B-C42 (design choice).** The local UI's live answers go through the coordinator: `ui.ask(question, lane, mode)`. Its own lane guess from the question's words (`choose_lane`) and its own fact sheet are removed. The page is unchanged; it does not yet offer the exact-answer switch, which belongs to the React application. Pooled coordinator runs are not listed for replay.

**Not done, and why.** E32 and E33 need Qwen3-8B on the desktop GPU. The command for E33:

```powershell
python -m graphrag.coordinator answer --questions prototype simulated heldout ak3_daily ak3_daily_heldout ak3_events ak3_events_heldout --name E33_coordinator_pool
```

The daily-report corpus is not on the laptop either, so the daily and event lanes were tested on stand-in chunks and events only.

## 2026-11-24: review of the lanes and the coordinator

An independent review of the day's code (a fresh reviewer, read-only) confirmed the two hard constraints by running them: `run_plan` gives the same text and events as before on all 154 plans recorded in `graphrag/results/`, and the baseline's requests are unchanged. It found eight defects, all fixed the same day, each with a test that failed first.

**B-F61 (finding; from replaying E28's recorded plans, no model call).** With the result reported by code (B-C39), the plans the model wrote in E28 score **33 of 35** on the seen set, where the two-call path scored 27 (`E28_graph_fixed_seen`), and **22 of 23** on the new set, where it scored 19 (`E28_heldout_graph`). The 22 matches the estimate E28 made and did not run.

- Nine answers change, all from wrong to right: t04, t13, t14, t23, t25, t30 and g07, g11, g13. Each had a right computed result that the answer call garbled or abstained on.
- This is not a new run. The plans are E28's, written under the planner's prompt; the coordinator's framing prompt adds two fields and may write different plans. E33 is the measurement.
- It is kept as a test (`RecordedPlanTests`), so a change to the event lane that loses these answers fails.

**B-C43 (design choice; fixes from the review).**

- **Exact mode and forced lanes.** `exact` now drops passages from a forced lane too. Before, the local UI's "end-of-well" choice in exact mode answered from passages.
- **Which names are wells.** The pattern for well names also matches a date range ("20-22 August") and a tool ("BHA-2"). Code now treats a name in a question as a well only if the engine holds it: a well its facts are about, one its reports are named after, or the event graph's well (`Engine.wells`). Before, "from 20-22 August 2016" replaced the plan's well and a right plan fell back to "not stated".
- **Frame types.** A frame whose plan fields have the wrong types is discarded for the empty frame. llama.cpp enforces the schema; a hosted endpoint may not.
- **Rows.** Rows answered without an answer call carry every key `answer_one` gives, so `baseline.summarize` reads a coordinator run.
- **Well-facts passages** are the chunks of each well's sheet lines, 12 per well, as B-C37 said; the first version took 12 times the number of wells overall.
- **Missing daily reports.** `Engine.has_daily`; a pooled run stops with a message if a daily or event question set is asked without them; the local UI says so when the daily lane is forced; and each row has `answered_from`, the reports its evidence came from, so a daily question answered from end-of-well passages is labelled as such.
- **Embedding server.** The local UI uses per-well BM25 for several wells when the embedding server is down, instead of failing.
- **Pooled runs** are refused by `compare_runs` and by the UI's replay, with a reason, instead of giving wrong tables or an error.
- `test_run_plan_text_is_unchanged` could not fail (it compared a function with itself). It now asserts the literal text of ten operations and replays the 23 recorded plans of `E28_heldout_graph` against their recorded results.

**Left open from the review** (small; none changes an answer today):

- `factgraph`: two facts with the same well, property, qualifier, context and value merge, and the last one's `source` and `unit` win; two actual casing values for one size would overwrite each other. No such pair exists in today's 216 facts.
- `factgraph`: `DESCRIBED_BY` links TG-2 and TG-4 to the AK-3 report (see B-F60).
- A question over time about a well without daily reports (56-32) falls back to AK-3's daily passages, because retrieval does not filter on a well no document names. This is the baseline's behaviour.
- The page `ui.html` does not show the lanes, the mode or the frame, shows `not_found_in_graph` as "not stated", and checks a fixed endpoint name. The React application replaces it.
- K4 0.2 writes `cost_usd` 0 for every coordinator row, also on a hosted endpoint; and writing K4 for a daily set needs the daily corpus to read the question text.
- The retriever cache and the UI's engine are shared between request threads without a lock.
- No test runs the command line's `main`.

## 2026-11-24: Hung's agreement, and backend work on his behalf

**B-D39 (decision, by Hung, told to Tri and relayed to Claude by Tri on 24 November).** Hung agrees with the design of the second build, including the graph model (D-67) and his role on backend and stores (Q14). He asked whether part of his work could be done for him for now, and Tri agreed: Track B does some backend tasks on his behalf and writes a detailed design for the others.

- **Done on his behalf:** the read-path API and its contract, and the question log (plan tasks B4, B5, B6), because the frontend, which is Tri's, cannot start without them. See B-C44.
- **Designed for him, not built:** shared hosting (B1), the runner (B2), loading the fact region into Neo4j and the event region on K1 version 1 IDs (B3), the question log in PostgreSQL, page images (B7) and the compose file with the access gate (B8). These need the stores or accounts that only he has. The design is [backend-design.md](../C-storage/backend-design.md), in his track's folder.
- Khai agreed to the data role the same day (B-D40).
- *Why recorded here:* the agreement reached Claude through Tri, not from Hung directly, and the Track C log is Hung's; a short entry there points back to this one.

**B-C44 (design choice; plan tasks B4, B5, B6, done on Hung's behalf under B-D39).** `backend/`, the read-path API of specification §7.5, as a FastAPI service.

- **Shape.** `schemas.py` holds the request and response shapes; `service.py` does the work without HTTP; `app.py` is routes and errors; `questions.py` is the question log. `create_app(service)` takes the service, so tests pass a small engine and stand-in models.
- **Endpoints:** `POST /v1/questions`, `POST /v1/questions/{id}/feedback`, `GET /v1/chunks/{id}`, `GET /v1/files`, `GET /v1/files/{id}/pages/{n}`, `GET /v1/wells`, `GET /v1/wells/{id}`, `GET /v1/wells/{id}/events`, `GET /v1/health`.
- **An answer carries** the lanes, the frame, whether it fell back, which reports answered, citations with their text and page, the evidence shown (passages, facts, the computed result with its events), the checks and the cost. For this the coordinator's rows gained `shown_passages` and `shown_facts`.
- **The contract** is generated from the code: `backend/openapi.json`, and ten example responses in `backend/fixtures/`. A test fails when they fall behind. The examples' evidence is real (the bundle, E28's events, the validated facts); their model is a stand-in, scripted in `contract.py`, and the README says so.
- **The question log** is a JSON-lines file under ignored `data/interim/backend/` for now: every question with its lane, frame, answer and cost, and feedback against its question ID. It holds what users typed, so it is not committed.
- **Reads files, not the stores.** `GET /v1/health` says `"source": "files"`. Reading the stores changes how the engine is loaded, not the service.
- **Errors:** an unknown ID is 404; a bad body is 422; a model server that does not answer is 503 with a message, not a crash. One question runs at a time.
- **Packages:** FastAPI 0.165.0 and uvicorn 0.54.0, pinned in `backend/requirements.txt`, apart from the main lock file so ingestion environments need no web framework.
- **Not built:** the page image (the page comes as its chunks' text), the PostgreSQL question log, login. Designed in [backend-design.md](../C-storage/backend-design.md) with the rest of Hung's tasks: shared hosting, the graph in Neo4j, the runner, the compose file and the access gate.
- **Checked without a model:** the example question "How many hours of non-productive time did AK-3 have?" computes 115 hours from 28 events on 10 dates, the figure the end-of-well report's own time table gives (115.0) and Track C counted in Neo4j (C-F06).
- 17 tests (`tests/test_backend.py`); they skip when FastAPI is not installed.

**B-D40 (decision, by Khai, told to Tri and relayed to Claude by Tri on 24 November).** Khai is fine with the data role for the second build: PDFs to K1 packages, table and form quality, the QA sidecar and new reports ([plan §2](../../DEVELOPMENT_PLAN.md#2-team-split)). With B-D39 the roles are settled for this stint: Khai data, Hung backend and stores, Tri the engine and the frontend. What is asked of Khai first is the demo release (plan task D1). Whether he has read the design itself is not known; the agreement recorded is to the role.

## 2026-11-24: the frontend

**B-C45 (design choice; plan tasks F1 to F4).** `frontend/`, the React application (React 19, TypeScript 5.9, Vite 8), built on `backend/openapi.json` and the example responses. It has not been run against a real model.

- **Screen.** An ask bar that stays at the top. On the left the answer: the value, one sentence on where it came from, the three steps of how it was answered (understood as, read, answered) with model calls and seconds, the sources, and right or wrong. On the right the evidence, as tabs.
- **Evidence.** For a computed number, one 24-hour strip per report day with non-productive time hatched, and the operations as a table; picking one marks the other. For a model's answer, the passages it read, cited ones first, with the answer's value marked where the report writes it (`1955` finds `1,955`), and the checked facts on their own tab. A source opens its page as text.
- **Words.** Every sentence the application says is in `src/lib/wording.ts`, and none names a lane or a frame. A computed answer says "No model wrote this number"; an answer that fell back says the daily operations held no match.
- **Type and colour carry meaning.** Report text is serif, the application's words sans, so the two are never confused. Amber is kept for non-productive time and warnings.
- **Other behaviour:** the graph-answers-only switch (D-59); a waiting state that counts seconds; earlier questions folded to one line and kept for the browser session; a link that carries a question (`?q=`); `/` to type, Esc to leave a page; light and dark by the system setting.
- **Types** are generated from the contract (`npm run types`). TypeScript is pinned to 5: the generator does not run on TypeScript 7.
- **Examples mode** (`npm run dev:examples`) serves the committed responses with no server and no model, and says so on screen. The examples are loaded only in that mode.
- 41 tests (`npm test`): the wording, the strip geometry, the highlighting, and the screen's flows with a stand-in API. Looked at in a browser in light and dark, wide and narrow.
- **Not done:** the page image, report titles, login.

**B-C46 (design choice; speed).**

- Backend: responses over 2 kB are compressed (an answer with its evidence is tens of kilobytes); reads may be kept by the browser for a minute and answers never; the question log keeps the IDs of logged questions in memory instead of rereading the file on each mark; the engine builds its chunk index once instead of per question.
- Frontend: the example responses are a separate file loaded on demand; fonts are bundled, so no outside request is made; the answer and the strips are not redrawn when only the question box changes.
- None of this was measured for time: the calls that dominate are the model's, and no model ran today.

**B-F62 (finding; seen in the application's "Checked facts" table).** AK-3 has a validated fact `spud_to_release_days = 3`, read by the model, while the report passage beside it says "a total of 19 days". The checks pass it because a 3 is written in its chunk: the value-in-chunk check cannot catch a small number that occurs for another reason. It is a wrong fact shown to the answer model, and one more reason to look at B-F60's doubts before the fact region is trusted. It was visible at once in the application and had not been noticed in the result files.

**B-C47 (design choice; from Tri's reaction to the first screens: "the user is not a dev").** The frontend is redone for non-developers. This replaces the look and the wording of B-C45; its behaviour and structure stay.

- **What was wrong.** The first version followed the system's dark setting, so it came up dark and technical on Tri's machine, and it spoke the system's language: "graph answers only", "operations", "1 model call".
- **Look.** Always light: white cards on a pale page, one blue for things to press, a rounder typeface (Plus Jakarta Sans). Report text stays in a serif. The dark theme is removed.
- **Words.** Rewritten in `src/lib/wording.ts`. "Graph answers only" is "Verified data only"; "operations" are "activities"; the evidence tabs are "Timeline", "Report text" and "Key facts"; reports are named as a person would ("AK-3 end-of-well report, page 7"). A test fails if the application says lane, frame, graph, chunk, token, model call, fallback or coordinator.
- **How far to trust an answer** is a coloured label on each one: calculated from the reports; written by AI and checked; written by AI and not confirmed; no answer found.
- **Explanations on hover.** A small "i" beside each label and term (`Tip.tsx`): hover, keyboard focus, or a tap that pins it. Bars of the timeline explain themselves on hover.
- **A guide** (`Guide.tsx`) opens on the first visit and from the top bar: what to ask, how to read an answer, how to check it, how to say it is wrong, with example questions asked in one click. It can be closed at once.
- **Each report is listed once** under an answer, where the first version repeated it for every passage.
- The technical trail and cost are still there, folded under "How we got this answer", for the supervisor and the team.
- Design guidance came from two installed design skills (a design-system search for a friendly light product, and its checklist: contrast, 40-pixel targets, visible focus, reduced motion, no emoji as icons). 49 tests; looked at in a browser, wide and narrow.
- **Still true:** it has not been run against a real model, and no domain expert has seen it. Whether it is intuitive for them is unknown until one uses it.

## 2026-11-24: stint report and notes to teammates

**B-C48 (design choice; documents).**

- **Stint reports have their own folder**, `docs/reports/stints/`, one report per stint, as Tri asked. The [report for 10 to 24 November](../../reports/stints/STINT_REPORT_2026-11-27.md) is written for anh Tuấn in the shape he asked for on 9 November: what he asked and where each stands, one picture, one question walked through, weak points, what we need. Tri's 5 November update moved there from this folder and is now `STINT_UPDATE_2026-11-05.md`; its links were fixed.
- **Requests to teammates are dated notes in their own track folders:** [for Khai](../A-ingestion/note-from-track-B-2026-11-24.md) (the demo K1 release with appendix 23, the legacy ID map and a well on end-of-well chunks; then the options, two more reports, the merged-cell defect, a dated log) and [for Hung](../C-storage/note-from-track-B-2026-11-24.md) (what was done on his behalf, his tasks in order with shared hosting first, four decisions that are his, and what to know before loading the well facts).
- The documentation index, the tracks index, the reports index, the plan, the specification and `CLAUDE.md` point to them.
- The stint report says plainly that most of the stint's work happened on 24 November, that there was no contact with the supervisor after 9 November, and that nothing new has run with a real model.

**B-C49 (design choice; the stint report as a draft with diagrams, and the root folder cleared).** From Tri's review of B-C48's first version.

- **The stint runs to 27 November**, so the report is `STINT_REPORT_2026-11-27.md`, marked as a draft and updated until then.
- **Removed from the report, at Tri's request:** the remarks in B-C48's version on when in the stint the work was done and on contact with the supervisor. A stint report says what was built and what is weak, not how the days were spent.
- **It now explains the system**, not only lists what was done: the four parts and who owns each, the path of a question step by step, and the knowledge graph, each as a diagram; three questions as the application shows them, as screenshots; and what Tri, Hung, Tri and Hung together, and Khai built. The backend service is described as Tri's and Hung's work together.
- **Diagrams are generated.** `scripts/stint_figures.py` draws three SVG files (plain SVG with real text, no outside fonts). A first attempt with Mermaid came out too small to read on a page and was dropped for the report; Mermaid stays the rule for the specification's diagrams.
- **A PDF is built from the Markdown** by `scripts/render_stint_report.py`: Markdown to a laid-out page, then printed by Edge or Chrome. The Markdown stays the source, and the PDF is committed beside it.
- **The notes to Khai and Hung are rewritten as work lists**: for each task, what to build, the steps, and how to know it is done.
- **Files moved out of the repository's root:** the slides of the professor's review to `docs/reports/slides/ARCHITECTURE_TODAY_2026-11-12.pdf`; the 27 October report's PDF from `output/pdf/` to `docs/reports/`, with its render script pointed there, and the empty `output/` folder removed; the English copy of VPI's requirement document, `KGinEP.docx`, to the ignored `docs/requirements/originals/KGinEP-en.docx`, beside the Vietnamese one.

