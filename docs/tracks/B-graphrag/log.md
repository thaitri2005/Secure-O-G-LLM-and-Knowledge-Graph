# Track B log

The dated record of Track B, the answering engine: what was found, decided and built, in the order it happened. For where things stand now, read the table below or the [plan](../../DEVELOPMENT_PLAN.md#current-status); for how the engine works, the [engine README](../../../graphrag/README.md).

| Prefix | Kind | What it records |
|---|---|---|
| **B-F** | Finding | Something learned from reading or from a run, with its source |
| **B-D** | Decision | What we chose, and why |
| **B-C** | Design choice | How a part is built: a setting, a prompt rule or an interface |
| **E** | Experiment | A link to the record in [`docs/experiments/`](../../experiments/README.md), plus one line on the outcome |

Entries keep their numbers for good. A later entry that replaces an earlier one says so; several same-day versions of one decision are folded into the last.

## Current state

| Topic | Where it stands | Entries |
|---|---|---|
| What answers questions | A coordinator sends each question to one of four lanes: passages, well facts, events, reasoning about causes. Built; the coordinator and the reasoning lane are not measured | B-D36, B-C37, B-C38, B-C51 |
| Passages | BM25 routed by well, top 5; per-well fusion for questions naming several wells; a date filter on daily reports. Qwen3-8B, thinking off; citations and values checked in code | B-D23, B-C21, B-C22 |
| Well facts | A per-well fact graph from table rules and model extraction, checked in code: 216 facts of 5 wells, 202 of them on the demo package's chunk IDs. Ties plain retrieval on new lookup questions so far | B-D29, B-C40, B-C64, B-F30 |
| Events | An event graph built from operations tables with no model call; the model writes a plan, code runs it and reports the total | B-D26, B-C39 |
| Best scores so far | 28/31 prototype questions (baseline); 30/31 with facts; 22/35 and 19/23 on totals over time against 5/35 and 4/23 for plain retrieval. All on questions written by the team | [E18](../../experiments/E18-well-routing.md), [E22](../../experiments/E22-table-facts.md), [E28](../../experiments/E28-event-graph.md) |
| Application | A backend and a frontend on the stores, behind one password; runs end to end on a laptop with a stand-in model | B-C44 to B-C47, B-C50 to B-C57 |
| Models | Qwen3-8B answers best; Qwen3-4B extracts; Qwen3-Embedding-0.6B embeds. Qwen2.5-7B and Llama-3.1-8B abstain and are dropped | B-D06, B-D14 |
| Bases tried | neo4j-graphrag-python and LightRAG were run and not adopted as bases | B-D21 |
| Ontology (K2) | Version 1.2, kept thin; no further ontology work | B-D17, B-D25 |
| Compute | None of our own. Rented, on public data only; a request for 5 million VND for three months is drafted | B-D42, B-D47 |
| Trying a model | A profile names a model on an address; `python -m graphrag.bench` checks it, runs the measurement suite and compares runs | B-D48, B-C60 |
| Questions | All simulated except the prototype's 31; none is expert-reviewed | B-D22 |
| Next | Compute, then the three measurements E32, E33, E34 with the bench ([commands](next-runs.md)) | B-D38, B-C60 |

## Contents

| When | What happened | Entries |
|---|---|---|
| 30 October | Scope, rules, the survey of ready-made GraphRAG code; first code and the retrieval baseline (E14) | B-F01 to B-F15, B-D01 to B-D10, B-C01 to B-C07 |
| 31 October | The desktop GPU; checks in code (E15); neo4j-graphrag (E16); the model sweep (E17); routing by well (E18); LightRAG set up (E19) | B-F16 to B-F22, B-D11 to B-D17, B-C08 to B-C14 |
| 1 November | LightRAG on three reports; per-well facts checked in code (E20, E21, E22) | B-F23 to B-F29, B-D18 to B-D21, B-C15 to B-C18 |
| 4 November | Simulated expert questions (E23 to E27); the supervisor's papers | B-F30 to B-F46, B-D22 to B-D25, B-C19 to B-C23 |
| 5 November | The event graph (E28, E29) | B-F47 to B-F54, B-D26 to B-D27, B-C24 to B-C27 |
| 9 and 10 November | Track A's K1 version 1 (E30, E31); the supervisor meeting; a simple UI | B-F55 to B-F58, B-D28 to B-D35, B-C28 to B-C34 |
| 24 November, morning | The second build designed; lanes, coordinator, fact graph export; a review | B-D36 to B-D38, B-C35 to B-C43, B-F59 to B-F61 |
| 24 November, midday | The backend, the frontend, the stint report | B-D39, B-D40, B-C44 to B-C49, B-F62 |
| 24 November, afternoon | All three tracks built toward production | B-D41, B-C50 to B-C57, B-F63 to B-F65 |
| 24 November, evening | No GPU of our own; the resource request; the documents reorganised | B-D42 to B-D47, B-C59 |
| 25 November | Everything that needs no compute: the model bench, vector search in the database, the question log's read side, three screens, three reports in the package | B-D48, B-C60 to B-C64, B-F66, B-F67 |

Search the file for an entry's number to find it.

## 2026-10-30

**B-F01 (finding).** A graph does not help on simple fact questions. GraphRAG-Bench (ICLR 2026) finds plain RAG equal to or better than GraphRAG there; graphs help on multi-step reasoning and as the corpus grows.

- Many of our questions are single-fact lookups ("what total depth did AK-3 reach?"), so every base is compared with plain vector RAG. Combined vector and graph retrieval is the likely winner.
- Source: [arXiv 2506.05690](https://arxiv.org/abs/2506.05690v3).

**B-F02 (finding).** On ~7B models, invalid structured output is the main failure. A study running Microsoft GraphRAG on local 7B models reports broken JSON and degenerate repetition; secondary sources say constrained decoding (a JSON schema or grammar) matters more than which small model is used. Sources: [arXiv 2605.20815](https://arxiv.org/pdf/2605.20815); [structured extraction](https://bestllmfor.com/best/structured-data-extraction-json/) (unverified).

**B-F03 (finding).** LightRAG's own documentation recommends large extraction models: Qwen3-30B-A3B-Instruct as the "reasonable minimum", a query model stronger than the extractor, and a warning that models under about 50 tokens per second can time out on dense chunks. This conflicts with the ~7B limit (D-37), so LightRAG on a ~7B model is a real test. Source: [LightRAG README](https://github.com/HKUDS/LightRAG).

**B-F04 (finding).** neo4j-graphrag-python matches the ontology-injection requirement directly. Its schema takes node types, relation types and allowed patterns; `additional_*` flags keep or prune undefined types. It supports structured output, links Document and Chunk nodes in a lexical graph, merges entities with the same label and name, and extracts once per chunk. Source: [KG builder guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html).

**B-F05 (finding).** neo4j-labs/llm-graph-builder is a finished application close to our M4 target: upload, schema settings, seven chat modes, sources in answers, per-user token limits. FastAPI and React on Neo4j, with Ollama and OpenAI-compatible models; Apache-2.0. Source: [README](https://github.com/neo4j-labs/llm-graph-builder).

**B-F06 (finding).** RAGFlow offers two extraction modes: "Light" (LightRAG prompts, fewer tokens) and "General" (GraphRAG prompts with repeated extraction rounds, known as gleaning). Its documentation says graph construction is token-heavy, especially with entity resolution and community reports; the cost goes to extra extraction rounds, entity-description summaries and community reports. Sources: [RAGFlow docs](https://ragflow.io/docs/construct_knowledge_graph), [DeepWiki](https://deepwiki.com/infiniflow/ragflow/6.4-graphrag-and-knowledge-graph-construction).

**B-F07 (finding).** fast-graphrag injects a domain cheaply: a domain description, a list of entity types and example queries. Retrieval uses personalized PageRank. It claims (self-reported) to be 6× cheaper than Microsoft GraphRAG on one book. Source: [README](https://github.com/circlemind-ai/fast-graphrag).

**B-F08 (finding).** Youtu-GraphRAG uses a seed schema at extraction time, to bound what is extracted, and at query time, to split a question into sub-queries. It claims (self-reported) up to 90% fewer tokens. Its licence is Tencent's own text, not yet read. Source: [arXiv 2508.19855](https://arxiv.org/abs/2508.19855).

**B-F09 (finding).** MiniRAG targets small models (Qwen2.5-3B, Phi-3.5-mini); retrieval relies on graph structure instead of a strong query model. Inactive since October 2025. Source: [arXiv 2501.06713](https://arxiv.org/pdf/2501.06713v2).

**B-F10 (finding).** Small LLM candidates. Which of them OpenRouter serves is not yet checked.

| Model | Size | Note |
|---|---|---|
| Qwen3-4B-Instruct-2507 | 4B | Reported 98.9% valid JSON (unverified) |
| Qwen2.5-7B-Instruct | 7B | Continuity with the prototype, which used Qwen2.5-3B |
| Llama-3.1-8B-Instruct | 8B | Slightly above "about 7B" |
| Qwen3-8B | 8B | Slightly above "about 7B" |

**B-F11 (finding).** Embedding candidates. Scores come from secondary rankings, so we choose by retrieval recall on our own questions. Sources: [theairankings](https://theairankings.com/best-embedding-models/), [premai](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/).

| Model | Note |
|---|---|
| Qwen3-Embedding-0.6B | Strong for its size |
| bge-m3 | Multilingual, useful if Vietnamese documents come later |
| EmbeddingGemma-300M | Smallest; possible |

**B-D01 (decision).** Start small: the 15 AK-3 EOWR chunks from the prototype, then the whole AK-3 EOWR; daily reports only after a base is chosen. The yardstick is the prototype's 31 questions and the E10 gold facts. *Why:* the supervisor asked to begin on one short document (D-44), and small runs are cheap to repeat.

**B-D02 (decision).** Efficiency is a headline metric. Every run records LLM calls, input and output tokens, wall-clock seconds, and cost per page and per question, next to quality. *Why:* large runs will be on ~7B models within booked GPU slots, so the cost per page decides what is feasible (D-38).

**B-D03 (decision).** Build plain vector RAG first, on the same chunks and questions. It costs only embeddings to index, and every base must beat it on quality or justify its extra cost. *Why:* B-F01.

**B-D04 (decision).** Run neo4j-graphrag-python first and LightRAG second. Learn from llm-graph-builder (application), RAGFlow (cost modes), fast-graphrag and Youtu-GraphRAG (cheap ontology injection) and MiniRAG (small models). Skip Microsoft GraphRAG (token-heavy), KAG and Graphiti as bases. *Why:* B-F03 to B-F09; [survey](survey.md).

**B-D05 (decision).** Ask the supervisor whether 8B models count as "about 7B". *Why:* Qwen3-8B and Llama-3.1-8B are the obvious candidates just above the limit.

**B-C01 (design choice).** One extraction pass per chunk: no gleaning rounds, entity-description summaries or community reports, unless a run shows the quality gain is worth the calls. *Why:* B-F06; these are the main token sinks.

**B-C02 (design choice).** Constrained JSON output: the provider's JSON-schema mode where OpenRouter supports it, a grammar (XGrammar in vLLM) on local serving. Invalid outputs and retries are counted as a metric. *Why:* B-F02.

**B-C03 (design choice).** Each extraction prompt carries only the ontology slice for the chunk's section. *Why:* shorter prompts on every call, and the specification's slicing design (§6.2).

**B-C04 (design choice).** Cache every model call by chunk hash, prompt version and model, so reruns cost nothing for unchanged chunks. *Why:* efficiency; LightRAG and the prototype already do this.

**B-D06 (decision; answers B-D05).** 8B models count as "about 7B"; Qwen3-8B and Llama-3.1-8B-Instruct join the LLM candidates. *Why:* confirmed by Tri on 30 October 2026.

**B-D07 (decision).** Every licence in the survey is acceptable with proper credit, including Youtu-GraphRAG's Tencent licence. Copied or adapted code keeps its copyright notice, and a `NOTICE` file next to it records the source repository, commit and licence. *Why:* Tri's decision on 30 October 2026.

**B-D08 (decision).** Adopt only what is close to our description, then make it better.

- We look only at solutions close to the 28 October description (ontology-guided extraction with small models, chunk provenance, graph and vector retrieval, a usable application) and improve them on drilling reports, for example with ontology slicing, cost per page, tables and review by exception.
- neo4j-labs/llm-graph-builder is studied when we need a part it has, such as schema settings, chat modes or token limits. We do not adopt it wholesale.
- *Why:* the supervisor asked to take over an existing pipeline and improve it (D-36, D-41).

## 2026-10-30 (evening): first code and the retrieval baseline

**B-C05 (design choice).** Code lives in [`graphrag/`](../../../graphrag/README.md): `client.py` (the model client for B-C02 and B-C04, plus the private-data guard, FR-28), `retrieval.py` (BM25, dense and fusion), `scoring.py` (the prototype's answer rules, so results compare with E10) and `baseline.py` (the command line). Endpoints are in `configs/graphrag/endpoints.json`; `tests/test_graphrag.py` holds 12 tests with no model calls.

**B-F12 (finding).** PyTorch on this laptop (Intel i5-1340P, 16 GB, CPU only) is unusably slow for embeddings: eight 200-token passages through bge-small (33M parameters) took 13–21 s, where about 0.1 s is normal. llama.cpp on the same CPU embeds about 18–80 tokens per second with Qwen3-Embedding-0.6B, depending on what else is running.

**B-C06 (design choice; follows B-F12).** All models, embeddings included, are served through OpenAI-compatible endpoints (llama.cpp locally) and called through the one client. The PyTorch embedding path was removed. *Why:* faster here, and it is how deployment will work (vLLM or llama.cpp on the school GPUs).

**B-F13 (finding).** llama.cpp's Vulkan backend on the Iris Xe integrated GPU runs out of device memory even for a 0.6B embedding model. `--device none -ngl 0` (CPU only) works.

**B-F14 (finding).** On AK-3, BM25 retrieves better than dense embeddings and is about 6,000× cheaper to index ([E14](../../experiments/E14-plain-rag-baseline.md)): hit@5 1.00 on the 60 AK-3 chunks, against 0.78 for Qwen3-Embedding-0.6B and 0.87 for fusion.

- Our questions name wells, depths and casing sizes, keywords BM25 matches exactly. Fusion with weak dense results drags BM25 down.
- Other reports hurt BM25 (hit@5 0.78 on 372 chunks of three reports), so filtering by document or well (the §5.11 ID payload) will matter before the corpus grows.

**B-D09 (decision).** BM25 is the retriever for the answer baseline; no dense retrieval over the 372-chunk pool on this laptop, where indexing it would take over an hour. Dense and hybrid retrieval are revisited on OpenRouter or the school GPUs, where embedding is cheap.

**E14 (experiment).** Plain RAG baseline: [E14](../../experiments/E14-plain-rag-baseline.md). BM25 over AK-3, top 5, Qwen3-4B-Instruct-2507: **21/31**, against 23/31 for the E10 prototype; about 1,400 prompt tokens and 100 s per question on the laptop.

**B-F15 (finding; from E14).** On one report, the 4B model's reading is the bottleneck. Every gold fact was among the 5 passages; seven misses were the model saying "not stated", four on table chunks. Model-written citations are unreliable: quotes were verbatim in only 5 of 15 answers.

**B-C07 (design choice; from B-F15).** Citations are attached or checked in code from the retrieved chunk IDs, never taken on trust from the model. Dates and numbers are normalized in code after the call.

**B-D10 (decision).** Next, run neo4j-graphrag-python on the same 60 chunks, questions and model, and compare it with E14 on correctness, citations, tokens and time.

- Rerun E14 with the B-C07 checks and *k* = 3 alongside, so the baseline is as strong and as cheap as it can be.
- Speed and cost comparisons move to OpenRouter once the key is set, because this shared laptop's timings are not comparable between runs.

## 2026-10-31

**B-D11 (decision).** Track B runs move to a bigger machine or to OpenRouter. The laptop's downloaded models were deleted (about 7 GB: `data/interim/models/` and the Hugging Face cache copies of Qwen3-Embedding-0.6B and bge-small). Machine setup and next steps are in [CLAUDE.md](../../../CLAUDE.md). *Why:* the laptop was too slow to compare runs (B-F12, E14), and a new session must be able to continue from the repository alone.

## 2026-10-31 (afternoon): desktop GPU and E15

**B-F16 (finding).** A desktop GPU makes Track B runs cheap enough to repeat.

- RTX 4080 SUPER 16 GB, Ryzen 9 9900X, 32 GB; llama.cpp b12015 (CUDA 12.4 Windows build), both models on the GPU in about 4 GB of video memory.
- The E14 answer run takes 25 s instead of 3,714 s on the laptop; indexing AK-3 with Qwen3-Embedding-0.6B takes 1.1 s instead of 614 s.
- E14 reproduced at 21/31 with identical prompt tokens. GPU decoding is not bit-for-bit repeatable (completion tokens differ by about 0.5%), so a difference of one question is noise.

**B-C08 (design choice; implements B-C07).** Citations and values are checked in code after the answer call.

- `graphrag/citations.py` keeps a model citation only if the chunk was retrieved and holds the quote. Otherwise it attaches the retrieved chunk holding the quote, then the value; otherwise the answer has no supported citation.
- `scoring.normalize` writes dates as `YYYY-MM-DD`, drops thousands separators and merges duplicate values. Raw model values stay in the result file.

**E15 (experiment).** Baseline with the code checks: [E15](../../experiments/E15-baseline-checks-in-code.md). BM25, *k* = 5, Qwen3-4B: **22/31** (E14: 21/31). Citations supported after the check: 16/17 answers, against 7/17 verbatim model quotes.

**B-F17 (finding; from E15; replaced by B-F18).** An answer with no supported citation seemed a usable signal to withhold it, flagging only the one hallucinated answer (q25). B-F18 found this wrong.

**B-D12 (decision; from E15).** The baseline stays at BM25 with *k* = 5 on one report; fusion of BM25 and Qwen3-Embedding-0.6B is used once a pool holds more than one report. It replaces the part of B-D09 that kept dense retrieval off, since dense retrieval is cheap on the GPU.

- *Why:* *k* = 3 loses two answers for 37% fewer tokens; fusion is the only retriever that holds up against distractor reports (0.91 against 0.78).

**B-D13 (decision).** Next, in order: (1) withhold answers without a supported citation, and measure it; (2) run Qwen3-8B and Qwen2.5-7B-Instruct locally, to size how much of the reading gap is the model; (3) run neo4j-graphrag-python as E16 (B-D10 step 2).

## 2026-10-31 (evening): neo4j-graphrag-python, models and a correction

**B-F18 (finding; replaces B-F17, which was wrong).** A supported citation does not mean a right answer.

- The one unsupported citation in E15 was q19's correct answer, flagged because `1955` did not match `1,955`. q25's wrong value, 0.25, is in the cited survey table on other rows, so the check passed it.
- Once the check ignored thousands separators, every E15 answer had a supported citation, and withholding unsupported answers changed nothing (22/31, [E17](../../experiments/E17-model-sweep.md)). The E15 record carries a correction note.

**B-C09 (design choice).** Track B services and environment.

- Neo4j 5.26 with APOC (needed by neo4j-graphrag's writer) runs from `configs/graphrag/docker-compose.yml`. It shares ports with the unchanged prototype compose file, so run one at a time.
- neo4j-graphrag 1.23 needs `pypdf>=6.19` while the main environment pins 6.1.1 for Track A, so its runs use `.venv-graphrag` from `requirements-graphrag.lock.txt`. `graphrag/baseline.py` stays in `.venv`.
- llama-server runs with `-c 32768 -np 4` (8k context per slot); `-c 8192` was too small for extraction prompts.

**B-F19 (finding).** Parallel requests to llama.cpp make results non-repeatable. Three cold runs of one extraction with 4 parallel requests gave recall 0.54, 0.85 and 0.85; one request at a time gave 0.854 three times, bit for bit. Server settings matter too: one sequential answer run scored 22/31 and 23/31 under two context settings.

**B-C10 (design choice; from B-F19).** Measurement runs send one request at a time, and each record states the server settings. `neo4j_kg.py` defaults to `--concurrency 1`; `baseline.py` is already sequential.

**E16 (experiment).** neo4j-graphrag-python on AK-3: [E16](../../experiments/E16-neo4j-graphrag-python.md). Default prompt, Qwen3-4B: recall **0.85** of 41 gold facts at about 2 calls and 4,500 tokens per page (E10's pipeline: 0.73 at higher precision). Facts under each passage cost 29% more prompt tokens and lowered the 4B model's answers from 23/31 to 21/31; Qwen3-8B stayed at 28/31.

**B-F20 (finding; from E16).** Small-model extraction is fragile: one prompt sentence moves recall between 0.37 and 0.85, and a bigger model can be worse (Qwen3-8B as extractor: 0.51). Prompt tuning on 41 facts would overfit.

**E17 (experiment).** Answer models and multi-report retrieval: [E17](../../experiments/E17-model-sweep.md). BM25, top 5, AK-3: Qwen3-8B (thinking off) **28/31**, Qwen3-4B 23/31, Llama-3.1-8B 10/31, Qwen2.5-7B 8/31; the last two abstain on nearly every answerable question. Three reports, Qwen3-8B: BM25 22/31, fusion **26/31**.

**B-D14 (decision; from E16 and E17).**

1. The plain RAG baseline is **Qwen3-8B with thinking off**, BM25 on one report and fusion across reports: 28/31 on AK-3, the bar for every base.
2. **neo4j-graphrag-python is not adopted as the base**: its graph does not improve answers on these questions. Its schema handling and provenance stay the reference for building a graph if one is needed.
3. Qwen2.5-7B and Llama-3.1-8B are dropped as answer models for this harness.

- *Why:* on single-fact questions over one or three reports, reading by a capable model beats an extracted graph, as B-F01 predicted.

**B-D15 (decision).** Next, in order:

1. Ask the supervisor for questions where a graph should help (across wells and reports, counts, comparisons), or for the expert set, since the 31 development questions are mostly lookups plain RAG already answers.
2. Filter retrieval by well or document (the §5.11 payload), to stop wrong values from distractor reports.
3. Run LightRAG (B-D10 step 3) with Qwen3-8B on the three-report pool, against the fusion baseline (26/31).
4. Try the library's own retrievers (vector-Cypher, Text2Cypher) only if step 1 brings questions that need them.

## 2026-10-31 (night): well routing

**B-C11 (design choice).** Retrieval can be routed by the well a question names.

- Every retriever takes an `allowed` chunk set, applied before ranking, as a vector-store payload filter would be. BM25 computes its term statistics over the allowed chunks only.
- `WellRouter` (`wells:<retriever>`) finds well names in the question (`AK-3`, `TG-2`, `56-32`; casing sizes like `4-1/2` are skipped) and allows only documents that name one. A question with no known well is not filtered.
- Each document's well names stand in for the §5.11 "well registry IDs" until Track C's registry exists; the router then reads the payload.

**E18 (experiment).** Well routing: [E18](../../experiments/E18-well-routing.md). Three reports, BM25 hit@5: 0.78 unfiltered, **1.00** routed with filtered statistics (equal to AK-3 alone). Qwen3-8B: **28/31** routed, against 26/31 for unrouted fusion, with no added calls or tokens.

**B-F21 (finding; from E18).** A filter must also scope the term statistics. Filtering a shared BM25 index after scoring under-weights terms rare in the target report and common in the others (hit@5 0.91 instead of 1.00).

**B-D16 (decision; from E18).** The multi-report baseline is BM25 routed by well, Qwen3-8B, top 5: 28/31 on three reports. It replaces fusion as B-D12's multi-report retriever; fusion stays for questions that name no well.

- *Why:* routing costs nothing and recovers the one-report result.
- Consequence: plain RAG is not hurt by more reports on one-well questions, so a graph must be judged on questions naming no well or several wells, or asking across reports (B-D15 step 1).

## 2026-10-31 (late night): LightRAG set-up, a probe across reports, K2 version 1

**B-C12 (design choice).** Answer prompts label passages by chunk number (`[c0005]`) only when all come from one report; mixed reports get full chunk IDs, because every report has a `c0005`. Single-report prompts are unchanged, so E14 to E18 and the request cache stay valid. `baseline.py` gained `--questions`, `--answer-format` and `--fresh` (bypass the cache, to re-measure under new server settings).

**B-C13 (design choice).** `graphrag/lightrag_run.py` runs LightRAG 1.5.7 (HKUDS, MIT) as a library, in its own `.venv-lightrag`.

- K1 chunks go in through `ainsert_custom_chunks`, and retrieved chunks map back to K1 IDs by text (0 unmapped in every run). LightRAG calls our client, so its calls are cached and costed, one request at a time (B-C10).
- `aquery_data` returns entities, relations and chunks, which go through the baseline's answer prompt, citation check and scoring, so only retrieval differs.
- Qwen3-8B runs with `-c 32768 -np 1` for E19, because LightRAG's prompts and default 30,000-token query context do not fit an 8k slot. The baseline under `-np 1` with `--fresh` gives the same 28/31, so the change is not a confound.

**B-C14 (design choice).** A cross-report probe of 9 questions, `graphrag/gold/cross_report_probe.json`: comparisons, a count, people shared across reports, planned against actual, a relation between wells. Gold comes from the three reports' text.

- A development probe, not an evaluation set (D-49); the expert set replaces it. It also shows the supervisor examples of graph-worthy questions (B-D15 step 1).
- Result rows now record `gold_facts_retrieved`, how many of a question's facts have a retrieved passage; "gold chunk retrieved" counts any one, which overstates retrieval across wells.

**B-F22 (finding).** The answer schema's field order makes the model abstain.

- Plain RAG answered 0/9 probe questions. On p08 ("injection in which well was 68-32 drilled to monitor?") the answer passage ranked first and Qwen3-8B still returned `not_stated`; with that passage alone, or two passages, it answered 58-32.
- Constrained decoding writes fields in schema order, and `status` comes first: the model decides whether to answer before writing anything, and more context pushes it to abstain.
- An `evidence_first` format (a short evidence note, then answers, then status) answers p08 and p03 (2/9) and keeps 28/31 on the 31 questions (q31 now right, q05 now wrong).

**B-D17 (decision).** K2 version 1, the thin ontology slice for end-of-well reports: [`configs/ontology/k2_eowr_v1.json`](../../../configs/ontology/k2_eowr_v1.json).

- 9 entity types, 13 relation types and 19 properties with units, each tied to the section headings where it appears; taken from the three reports' headings and table columns and the prototype's 14 properties (unchanged).
- 104 glossary entries generated in code (`python -m graphrag.ontology glossary`) from the abbreviation and unit tables; four from merged cells are flagged for a person (`JSA jt`, `LGS LOT`).
- `python -m graphrag.ontology guidance` renders the slice as LightRAG's `entity_types_guidance`, the injection point for an ontology arm.
- *Why:* D-49 (thin, from the reports themselves) and B-D15 step 4. Not reviewed by a domain expert.

## 2026-11-01: LightRAG on three reports, and per-well facts

**E19 (experiment).** LightRAG against the baseline: [E19](../../experiments/E19-lightrag.md). LightRAG `mix` scores 25/31 against the baseline's 28/31, at 13,600 to 15,300 indexing tokens and about 22 s per page, and 1.6 to 6 times the baseline's prompt tokens per question. Probe: 3/9 each for plain RAG and LightRAG, on different questions.

**B-F23 (finding; from E19).** LightRAG's graph answers other questions than plain RAG, and no more of them. It links a person across reports (p05, Mary Mann) and gathers one value from every well (p02), which passages alone do not; it loses p06 and confuses TG-2 with TG-4 (q03). The default 30,000-token budget answers fewer probe questions than the small one.

**E20 (experiment).** Per-well facts as answer context: [E20](../../experiments/E20-well-fact-sheet.md). neo4j-graphrag with Qwen3-4B on three reports: 2.5 calls and 4,750 prompt tokens per page, AK-3 recall 0.56 (E16: 0.85). Adding each named well's facts before the passages: 28/31 to **21/31**, probe 3/9 to **1/9**.

**B-F24 (finding; from E20).** Unvalidated extracted facts make answers worse: contradictory values (three rig-release dates for AK-3) pull the model off the right passage. Facts must pass validation (§6.2 stage 6) before they reach the answer model.

**B-D18 (decision; from E19 and E20).**

1. **LightRAG is not adopted as the base.** The D-50 baseline stays: plain RAG, Qwen3-8B, BM25 routed by well.
2. Graph value is to be shown on questions across wells and reports, through the probe (B-C14) and the supervisor request ([ask-supervisor-graph-questions.md](ask-supervisor-graph-questions.md)).
3. Next: LightRAG with K2 injected (E21), to see whether our ontology makes its graph precise enough; then validation of extracted facts (verbatim value in the cited chunk, unit, one well name per registry entry) before any reaches an answer.

**B-C15 (design choice).** `graphrag/validate.py` checks extracted facts before they reach an answer (§6.2 stage 6, B-F24): the value is written in its source chunk; the well name resolves to one well its own document names; zeros (empty form fields) are dropped; per well, property, qualifier and context the best-supported value wins, and a tie drops the key. Rejections are counted by reason. `baseline.py --fact-sheet <graph> --validate` uses it.

**B-F25 (finding; from E20).** Validated per-well facts help on questions across wells without hurting single-well questions.

- Validation keeps 96 of 737 facts (146 values not in their chunk, 134 zeros, 128 without one well name, 127 contradicted, 28 with a well foreign to their document).
- Validated sheet: 28/31 (raw sheet 21/31) and **5/9 on the probe** (no sheet 3/9, raw 1/9, LightRAG 3/9).
- Caveats: one run, 9 team-written probe questions, an extractor with 0.56 AK-3 recall.

**B-D19 (decision; from E20; replaced by B-D24, which B-D29 reversed).** The working design is plain RAG (D-50) plus a validated per-well fact graph, used for the wells a question names.

- The graph is extraction (any base that keeps chunk provenance) followed by validation in code; nothing unvalidated reaches an answer.
- To confirm on the expert set before it becomes the chosen base. Next: extraction recall (K2 slice, table rows mapped deterministically), then people and projects (p05) and document counts (p07), which the 14-property profile does not cover.

**B-F26 (finding; from E20; corrected by B-F27).** neo4j-graphrag extraction with Qwen3-4B looked unstable across server restarts, even with identical requests.

- AK-3 alone, one request at a time: recall 0.561 under `-c 16384 -np 1` and again under E16's `-c 32768 -np 4`, where E16 recorded 0.854 with the same 113,964 prompt tokens. Most of the gap is one survey table (26 against 12 inclination facts).
- Consequence: one extraction run is not a measurement. Report recall as a range over runs, and never let extracted facts reach answers unvalidated (B-C15).

**B-F27 (finding; corrects B-F26).** Today's extraction runs are repeatable; E16's recall is the one that cannot be reproduced. A second fresh three-report run (`E20_graph_three_qwen3-4b_run2.json`) gave the same 737 facts and recall 0.561, and pooling the two runs changes nothing. E16's file does not record its concurrency. Take this extractor's recall as 0.56 until a run shows otherwise.

**B-C16 (design choice).** K2 carries deterministic `table_mappings`, applied by `graphrag/tables.py` with no model call: series tables (inclination, projected temperature, casing depth by size) and row tables (productive, non-productive and total rig time). Headers match as whole words; the well is the document's most-named well; "Planned" in the caption sets the qualifier; each fact cites the chunk holding its row.

**E22 (experiment).** Table facts: [E22](../../experiments/E22-table-facts.md). AK-3 fact recall: tables 0.68 with 0 calls, LLM 0.49, both 0.78 after validation. Answers with the validated sheet from both: **30/31** (only q05 wrong); table facts alone 26/31.

**B-F28 (finding; from E22).** Tables and prose need different extractors: tables give the series (inclination, casing, rig time) exactly and for free; the LLM gives well-level values written in prose (total depth, dates). Neither alone matches the two together.

**B-D20 (decision; from E22).** The fact graph of B-D19 is built from two validated sources: K2 table mappings (no model call) and LLM extraction for prose. Next: check the mappings on reports they were not written from (daily reports, new end-of-well reports), and extend them with Track A's table output (K1 version 1).

**B-C17 (design choice).** Table mappings find header rows from content (leading rows where under a quarter of the cells are bare numbers) and accept only headers of at most 50 characters, because the parser's header counts are wrong on 56-32 and 68-32's daily-report forms come out as grids of paragraphs.

- `--sheet-properties N` shows only the facts of the N K2 properties whose definitions best match the question (Qwen3-Embedding-0.6B).
- K2 gained `spud_to_release_days` and `total_rig_time` from the prototype profile; `scoring.normalize` reads `09-Mar-19`.

**B-F29 (finding; from E20 and E22).** The cross-report probe cannot separate setups: six fact-sheet variants scored 1, 2, 2, 3, 4 and 5 of 9, and answers flip with context alone (56-32's survey lines flipped p03 and p04). The single-well result is stable: 30/31 with three validated sheets. Judging graph value across wells needs the expert set or a larger probe.

**B-C18 (design choice).** K4 version 0.1, the answer record Track B publishes for Track C (§4.5): [`schemas/k4_answer_record.schema.json`](../../../schemas/k4_answer_record.schema.json).

- One JSON line per question: ID and text, status, normalized values with units, citations as child chunk IDs with how each was checked (B-C08), the pipeline (base, retriever, *k*, fact sheet, validation, answer format), the answer model, and the answer call's calls, tokens, seconds and cost; `correct` when there is gold.
- `python -m graphrag.k4 <run>` writes `graphrag/results/<run>.k4.jsonl`. The first file is from E22's run (31 records, valid against the schema).
- Chunk IDs are K1 version 0 until Track C's §5.11 IDs replace them. Index-time cost stays in the result file and experiment record.

**E21 (experiment).** LightRAG with K2 injected: [E21](../../experiments/E21-lightrag-k2.md). K2 as `entity_types_guidance` gives 925 entities and 1,385 relations, against 2,114 and 3,099 by default, at the same extraction cost (15,900 tokens per page). Answers 26/31 (defaults 25/31); probe up to 4/9, answering p07, the report count, for the first time.

**B-D21 (decision; from E19 to E22).** Close the base comparison for this stint.

1. **No GraphRAG base is adopted wholesale.** The working design (B-D19, B-D20) is plain RAG routed by well, plus a per-well fact graph from K2 table mappings and LLM extraction (neo4j-graphrag as the extractor), validated in code: 30/31 on the development questions.
2. **LightRAG with K2** stays the candidate for document, project and people structure (p05, p07), to test again when expert questions ask for it.
3. The open decision moves to the supervisor: 30 or more graph-worthy questions are needed to judge graph value across wells (B-F29). Until then Track B works on fact-graph coverage of people, projects and documents, and on Track A's K1 version 1.

## 2026-11-04: simulated expert questions

**B-D22 (decision; narrows D-49).** The supervisor asked the team to wait for the expert questions, so Track B uses a simulated set until they arrive: [`graphrag/gold/simulated_expert_v0.json`](../../../graphrag/gold/simulated_expert_v0.json). The reason: the graph's value and the pipeline's general quality cannot be judged on the 31 lookups (B-F29).

- Written by Claude at Tri's request. No drilling expert has reviewed it, so results are always reported as "simulated set", never as expert validation.
- 40 questions on the three end-of-well reports: 22 single-fact lookups in prose or tables, 4 on daily reports (68-32 appendices), 8 comparison, cross-report, multi-hop or count, 1 depth stated two ways in one report, 5 that must not be answered (not stated, off-topic, injection).
- Frozen before any run; changes go into a new version. A test confirms each non-derived gold value is written in its cited chunk, and the "not stated" questions were checked by search.
- Limits: it comes from the same reports as the table mappings, so it does not test them on unseen reports, and it is small, so a difference of a question or two is noise.

**E23 (experiment).** Working design against plain RAG on the simulated set: [E23](../../experiments/E23-simulated-set.md). Plain RAG and the design both score **29/40** (0 and 1 wrong values); per-well fusion gives 31 and 30, with 5 wrong values each.

**B-F30 (finding; from E23).** The fact graph does not improve answers on the simulated set: the top-5 setups tie with the same 11 misses, and the per-well setups differ by one question. E22's gain on the 31 questions does not carry over. Building the graph costs 2.48 LLM calls per page.

**B-F31 (finding; from E23).** The sheet rarely holds what is asked: 4 of 35 gold values are in it on a gold chunk. K2's facts have no rigs, people, companies, rotary Kelly bushing heights or casing grades. This supports B-D21's coverage work without showing that coverage would help.

**B-F32 (finding; from E23).** `validate.py` passes facts with the wrong meaning, because it checks only that the value is in the chunk. All 13 of 68-32's kept `casing_depth` facts come from the LLM, none gives the true 978 ft, and their sizes include `10031` (the rig number) and `1-39` (a time code). s33's wrong answer comes from such a fact and AK-3's planned depth. B-C15's checks need to cover context and qualifier.

**B-F33 (finding; from E23).** Per-well fusion with evidence first trades errors: cross-report questions go from 0/3 to 2/3, wrong values from 0 to 5, prompt tokens up about 2.3 times. Used only for questions naming several wells, it would give 31/40 with 1 wrong (plain) and 32/40 with 0 wrong (design). Those figures are computed from existing rows, with the rule chosen after seeing them, and need a real run on new questions.

**B-F34 (finding; from E23).** Two flaws in how the simulated set is measured. s02's gold (1.75°, from prose) conflicts with the survey table, which ends at 2° at 1,900 ft; the set stays frozen, so the fix goes into the next version. `gold_facts_retrieved` counts a fact as found when any one of its chunks is retrieved, which overstates retrieval on comparisons.

**Open, for Tri (from E23).** No decision changes yet: D-50 stays the baseline, and the working design is neither confirmed nor dropped. Recommended order: route by the number of wells named and test it on new questions; tighten the validator (B-F32); add coverage only after those two, since coverage alone would feed more unchecked facts to the model.

**B-C19 (design choice).** E24's gold names PDF pages and was written from the rendered pages before parsing, so it does not inherit parsing errors. `data.chunks_on_pages` maps pages to any parser's chunks. `graphrag/oracle.py` bypasses retrieval and gives the model the gold value's source page, to separate parsing, retrieval and model failures. It reads gold data, so it is a diagnostic only.

**E24 (experiment).** Plain RAG on the AK-3 daily reports, simulated questions: [E24](../../experiments/E24-ak3-daily-reports.md). BM25 routed by well, top 5: **5/30**; fusion, top 10, evidence first: 9/30 with 13 wrong values.

**B-F35 (finding; from E24).** On daily reports, retrieval and the answer format lose the most. Filtering by well does not separate days, questions write dates differently from the forms, and 630 of 898 chunks have no date in their text or section. With the right page given, status first gives 11/30 and evidence first 19/30, which confirms B-F22 on forms.

**B-F36 (finding; from E24).** Parsing sets the ceiling on daily reports: 9 of the 27 gold questions fail even with the right page, because form headers are read out of order, form regions lose their table structure, and some printed values are missing. Operations, mud and survey tables work (6/6 with the right page). The list for Hung is in the record. K1 version 1 needs key-value pairs from form headers and a report date on every chunk.

**B-F37 (finding; from E24).** Corpus pipeline problems for its owners: `process --workers 2` hung after exactly 40 documents in two runs (`max_tasks_per_child=20`; the cause is inferred, not traced); `scripts/run_ak3_appendices.py` prints "done" after every document fails and does not retry; `appx-04` now fails validation, though E8 processed it on an earlier commit.

**B-F38 (finding; from E24).** One answer changed between the first run and the uncached repeat, one request at a time (d20, from a wrong `1955` to an abstention; the score stayed 5/30). B-F19's rule is necessary, and it does not guarantee identical answers here.

**B-C20 (design choice).** The request to Track A is a file: [note-for-track-A-daily-reports.md](note-for-track-A-daily-reports.md).

**E25 (experiment).** Table mappings on an unseen report, 78-32: [E25](../../experiments/E25-table-mappings-unseen-report.md). As written: 3 facts, right depths, 2 with the wrong size, a 20-row survey missed. After two general fixes: 23 correct facts, no change on the original three reports.

**B-F39 (finding; from E25).** E22's caveat was real: written from AK-3, the mappings got most keys wrong or missed the table on an unseen report. One unseen report from the same project is one sample.

**B-C21 (design choice).** Routing and strict facts, as opt-in flags so earlier runs stay reproducible. `--multi-well-retriever`: questions naming several wells use per-well fusion, top 10, evidence first. `--strict-facts`: a casing size must look like one and be in the fact's chunk, the value must differ from it, a depth context must be in the chunk, and planned facts are hidden unless the question asks about a plan. K4 records give the pipeline each question used.

**E26 (experiment).** Routing and strict facts on 36 new simulated questions: [E26](../../experiments/E26-routing-and-strict-facts.md). Top 5: 20. Always per well: 23. **Routed: 23, with 30% fewer prompt tokens.** Fact sheet, routed: 21; with strict facts: 23.

**B-F40 (finding; from E26).** Comparison questions are unsolved: 0/5 in every setup. The model abstains, returns the numbers instead of the well, or picks the wrong well. Comparing values in code is the candidate, not yet tried.

**B-F41 (finding; from E26).** `WELL_NAME` does not match a well name followed by a period ("Well 68-32."), so such a mention is not routed. Not fixed, because a fix could change baseline results; test it on its own.

**B-C22 (design choice).** `dates:<retriever>` filters by the report date a question names. `page_dates` reads `Report For`, then the date another attachment gives the page's `Report No`, then the previous page's date: 143 of 145 pages right against the PDFs' text. A stand-in until K1 version 1 carries report dates.

**E27 (experiment).** Date filter and added coverage: [E27](../../experiments/E27-date-filter-and-coverage.md). Daily reports, 26 unseen simulated questions: 7 without the filter, **14 with it (wrong values 3 to 2)**, 17 with top 10 and evidence first (6 wrong). K2 version 1.1 added 24 facts with no model call and changed nothing measurable.

**B-F42 (finding; from E27; corrects a sentence in E24).** E24's right-page diagnostic is not an upper limit for better retrieval: 21/30 exceeds its 19/30, because the filter shows several attachments' copies of a day, and one copy may parse better than another.

**B-D23 (decision, by Claude, delegated by Tri on 4 November).** The baseline for this stint, replacing D-50's retrieval settings:

| Reports | Questions | Setting |
|---|---|---|
| End-of-well | Naming one well, or none | BM25 routed by well, top 5, status first |
| End-of-well | Naming several wells | Per-well fusion, top 10, evidence first |
| Daily | Naming a date | The same, with the date filter |

- *Why routing:* the same score as always per well at 30% fewer tokens, and 3 more right than top 5.
- *Why status first on daily reports:* evidence first gains 3 of 26 and gives 3 times the wrong values; a wrong number is worse than "not stated".
- *Cost accepted:* routing raises wrong values on held-out questions from 5 to 7.
- *Revisit when* the expert questions arrive, or K1 version 1 changes what forms look like.

**B-D24 (decision, by Claude, delegated by Tri on 4 November; replaces B-D19 to B-D21's working design; reversed by B-D29).** The fact graph leaves the baseline and stays as an option.

- *Why:* on questions written after it was designed it ties plain RAG (E23: 29 and 29; E26: 23 and 23; E27: 23 and 23) at 2.48 LLM calls per page. Its gain appears only on the prototype's questions, which shaped it, and efficiency is a headline metric.
- *Kept:* the code, `--strict-facts` and the table mappings, which cost no model calls. *Stopped:* further LLM extraction and coverage.
- *Limit:* the supervisor's direction expects a graph. This is about the answer pipeline on our simulated questions, not a verdict on graphs across wells; **the expert question set decides it for good.** Tell the supervisor at the next check-in.

**Track B has no run waiting.** What comes next depends on others: [next-runs.md](next-runs.md).

## 2026-11-04: papers from the supervisor

The PDFs are not kept in the repository, because of their copyright terms.

**B-F43 (finding).** Queiroz et al., "An Ontology of Well Engineering Entities to Extract and Structure Text Data from Daily Reports", SPE/IADC-223801-MS, 2025 (Petrobras, UNESP, Unicamp). DOI 10.2118/223801-MS.

- *What it builds:* a graph of **events**, not of per-well properties. Each operational log entry becomes an Activity linked to the components, fluids and properties observed in it; `Observed{Class}` nodes let one entity have different values at different times.
- *How it extracts:* regular expressions per class (stored in the ontology), part-of-speech tagging checked against a lookup table for activities, and relationship heuristics; regex was chosen over Transformer models for accuracy. LLMs only propose candidates for human review; LLM extraction is future work.
- *How it evaluates:* Competency Questions written first (incident counts per intervention, trip time rates, well status at a given moment), answered with SPARQL.
- *Limits:* no numbers, only "high levels of recall and precision" and "improved" against raw text, and no comparison with plain RAG, so it neither supports nor contradicts B-D24. About 2,300 classes from 129 wells and about 145,000 log entries took experts several months. Reports in Portuguese; no link to the ontology.

**B-F44 (finding).** Maucec and Khawaja, "Knowledge Graph-based Petroleum Engineering Ontological Framework for Well Performance Assessment", 87th EAGE Annual Conference (Saudi Aramco). An OWL ontology with SWRL rules and a reasoner classifies 300+ wells from a performance study into 6 classes. Reservoir side only, with drilling named out of scope; no documents, retrieval, LLM or accuracy figures. One idea applies: derived values are computed at query time by rules, not stored.

**B-F45 (finding; our reading of B-F43 against E23 to E27).** Our fact graph may have been tested on the wrong shape of graph and question: per-well static properties against mostly single-fact lookups, which retrieval already answers. The paper's graph targets counts, rates and states across many log entries, which retrieval cannot assemble, and our operations tables are the part of daily reports that parses well (E24). Proposed test: events from operations-table rows with no model call, and competency questions frozen first (hours by activity code, non-productive time, depth on a date).

**B-D25 (decision; from the supervisor, relayed by Tri, 4 November).** No ontology work for now: the direction is GraphRAG. B-F43 and B-F44 are background only; their methods (OWL, Protégé, reasoners, large class hierarchies, upper-ontology alignment) are not adopted, and D-49's thin K2 stays as it is. B-F45's event idea, if tried, must be a thin graph for GraphRAG answers, with no new ontology.

**Open, for Tri and the supervisor.** "GraphRAG for now" sits uneasily with B-D24, which takes the fact graph out of the baseline. B-D24 stands on the numbers until the supervisor has seen them; he may prefer a graph in the main pipeline regardless.

**B-F46 (finding; corrects a reading in the session of B-F43).** The supervisor sent the two papers before his GraphRAG direction, so they do not signal what he expects now. B-D25 stands: they are background.

**B-C23 (design choice; documents brought up to date).** The specification (version 3.2, with a new §8.4 on what the first build runs today and its architecture diagram, and D-52), the plan, `CLAUDE.md` and `graphrag/README.md` now state what runs today. Removed as superseded: the "working design" as the current design, "LightRAG with K2 next", "the team writes no question set of its own", and the `-np 4` server command, now `-np 1`. §8.1 to §8.3 stay as the GraphRAG target, because the direction has not changed.

## 2026-11-05: the event graph

**B-C24 (design choice).** `graphrag/events.py` builds a graph of wells, report dates, events, activity codes and non-productive codes, with no model call, from operations tables merged across attachments and joined with appx-23 by date and time.

- The model writes a JSON plan, code runs it, and the model writes the answer from the result and the source passages.
- Kept in memory, not in Neo4j; no new ontology (B-D25). K4 gains `how: event_graph` for chunks holding a computed result's source events.
- `page_dates` is fixed: 145 of 145 pages.

**E28 (experiment).** Event graph on questions over time: [E28](../../experiments/E28-event-graph.md). Simulated questions, chosen to suit it; 161 of 161 events match the PDFs' text layer. Frozen 35: **22** against 5 at best for plain RAG. New 23, after a planner fix: **19** against 4. 26 daily lookups: 17 against 14.

**B-F47 (finding; from E28, answers B-F45).** The shape of the graph has to match the questions. Static per-well facts duplicate what retrieval finds; events add what it cannot do, because plain RAG sees five to ten passages and cannot add up 27 days.

**B-F48 (finding; from E28).** The final model step garbles right results: on the new 23, the graph's result held the gold value on 19 of 20, and 16 were answered correctly (g07: result 6.5, answer 4). Reporting the result in code would give 22/23, computed and not run.

**B-F49 (finding; from E28).** No single daily-report source is complete. Summaries omit rows ("1 record not printed"), each attachment loses some, and the parser loses `X` marks and turned a one-row table into text. Merging them and joining appx-23 recovers all 161 rows.

**B-D26 (decision, by Claude, delegated by Tri; revises B-D24 for this kind of question).** Questions over time on daily reports are answered from the event graph; other questions fall back to retrieval. This is D-53.

- *Why:* a wide margin on two question sets, no LLM call to build, and no harm to lookups. It also fits the supervisor's GraphRAG direction.
- *Cost accepted:* 2 LLM calls per question and about 900 more prompt tokens.
- *Limit:* the questions were chosen to suit it, and it covers one well and one report system. **Whether users ask such questions is for the supervisor and the expert set.** B-D24 stands for the per-well fact graph.

**E29 (experiment).** Table mappings across reports from other authors: [E29](../../experiments/E29-table-mappings-across-reports.md). Fixes from one report, tested on the others. Held-out casing strings: 4/16 as written, **13/16 after fixes and validation (0 wrong facts)**. Survey rows on the held-out report: 81 of 198 after validation, 7 wrong.

**B-F50 (finding; from E29).** As written, the mappings found nothing outside GRG's layout, though they stated nothing false. The causes were general: well names with several parts, an `Item` column, Unicode fractions, and a depth column named `MD`.

**B-F51 (finding; from E29).** Metre depths would have been labelled as feet. Facts now carry `unit`, and metre surveys use `depth_m`.

**B-F52 (finding; from E29).** The strict validator (B-C21) discarded right facts, because it looked for `13-3/8` in text saying `13 ⅜"`. The raw score looked good while almost nothing reached the model, so table results must also be scored after validation.

**B-F53 (finding; from E29).** Surveys from these reports are not reliable: half the rows at best, and 8% of validated rows wrong on the held-out report, because the parser merges dense tables. Scanned reports are out of reach: Raft River comes out column by column. Both are for Track A.

**B-F54 (finding; from E29).** There is still no evidence on a different author's modern digital report. Three of the five held-out reports share a consultant with the dev report, and the one different author is a scanned 1976 report, which fails.

**B-C25 (design choice).** `graphrag/table_eval.py` scores table facts against independent gold, raw and after strict validation. K2 version 1.2 adds `casing_items`, `number_cells`, `max_step` and `depth|md`. `WELL_NAME` reads names with several parts (`TNT-GT-01`, `HON-GT-01-S2`). Well names on the original three reports are unchanged, and those reports lose only 4 junk facts.

**B-C26 (design choice).** Tri's status update for the supervisor is kept in the repository: [STINT_UPDATE_2026-11-05.md](../../reports/stints/STINT_UPDATE_2026-11-05.md) (moved to the stint reports folder on 24 November). It reports E23 to E29, the limits, and that all questions are AI-written; it asks for a specification to write development questions from, and whether users ask questions over time.

**Stint closed on 5 November.** No Track B run is waiting; next steps depend on the supervisor's reply, Track A's K1 version 1 and Track C's stores ([next-runs.md](next-runs.md)). On our side: let code report the event graph's result directly, try the event graph on 58-32's daily reports, and try a different author's modern report.

**B-D27 (decision, by the team; told to Claude by Tri).** From 5 November, Track A (ingestion and tables, K1) is Khai's and Track C (storage, IDs, end-to-end run) is Hung's; Track B stays with Tri. Requests to Track A, including K1 version 1 and [the note](note-for-track-A-daily-reports.md), go to Khai; choosing the vector store and loading Neo4j go to Hung. Current documents, [next-runs.md](next-runs.md) among them, carry the new names; dated log entries (B-F36) and the meeting records keep the names used at the time.

**B-C27 (design choice).** Tracks A and C now carry Track B's findings: a "What Track B found" block in each of their plan sections, end-of-well findings and the K1 fields Track B reads in [the note to Track A](note-for-track-A-daily-reports.md), and [a new note to Track C](note-for-track-C-storage.md) on what runs today, what the stores need and which code depends on today's IDs. Removed from Track C's plan: choosing the vector store by "the chosen GraphRAG base" and researching candidate pipelines' storage (no base was adopted, B-D21), and writing a K4 schema (0.1 exists, B-C18). This is Track B's view; each owner can change their own plan.

## 2026-11-09: Track A's K1 version 1 candidate

Khai pushed Track A's work to the branch `track-a-k1-package` (14 commits, 81 files): the K1 version 1 candidate ([E30](../../experiments/E30-k1-version-1-candidate.md)), Operations Summary tables rebuilt from the PDF text layer, quality checks and a table-extraction benchmark. Claude reviewed it and merged it into `main` at Tri's request: no conflicts, 614 tests pass (11 skipped).

**B-C28 (design choice; from E30).** `graphrag` reads both chunk ID formats: K1 version 0 (`<doc_id>#c0005`) and Track A's version 1 candidate (`f<hex>:s6:c0`, no `#`). `graphrag.data` gains `document_key`, `short_id` and `cited_id`, replacing the four places E30 found splitting on `#`. Version 0 runs give the same IDs as before. `scripts/check_k1_graphrag_compat.py` now reports no gaps.

**B-C29 (design choice; from E30).** K2's `sources` name K1 version 0 table IDs. Table mappings match tables by their headers, so they run on a version 1 package as they are. Only `python -m graphrag.ontology glossary` reads `sources`; it now also matches a table's `logical_id`, where version 1 keeps the version 0 ID. That holds only while a new run numbers tables as the old bundle did, so check the glossary after regenerating it from a new package. From `data/processed/gdr_tables.jsonl` it gives the same 104 entries; K2 is unchanged.

**B-F55 (finding; from reviewing E30).** Three things in E30 are not settled by code:

1. **Retrieval drops on the new chunks:** BM25 hit@5 on the prototype questions is 0.913 with `rapidocr`, against 1.000 on the old bundle (Khai's measurement). q03's gold chunk was cut differently, and on q11 an OCR chunk of a figure outranks the gold chunks. Answers were not run; Track B reruns E17's baseline once the package is shared.
2. **The package is not in the repository.** E30 links a sample in `data/processed/k1/ak3-k1-candidate/`, but no file there is tracked, so the numbers cannot be rerun here yet.
3. **The ID scheme.** The plan gives §5.11 to Track C, and Hung's log says to agree it with Track B first. E30's IDs (`<file_id>:s<n>:c<n>`, tables `<file_id>:t<n>`) and six `k1_*` schemas are Track A's proposal, beside Hung's `k1_chunk.v0` without conflict. Track B's code reads either; Hung decides.

**B-D28 (decision, by Tri; answers B-F55 item 3). This is D-54.** Chunk and table IDs follow specification §5.11 in the format Track A's K1 version 1 writes (E30): `f<first 16 hex of the PDF's SHA-256>` for the file, then `:p<n>` page, `:t<n>` table, `:s<n>` section parent, `:f<n>` form parent, and `<parent>:c<n>` child chunk.

- *Why:* it is already the format of §5.11, built and tested. The file part hashes the PDF bytes, so an ID survives a rename, and a rechunk changes only the child part; version 0's `<doc_id>#c<nnnn>` renumbers on any rechunk.
- *Cost accepted:* gold written against version 0 IDs (`prototype/gold/ak3_facts.json`) goes through the old-to-new map, which E30 measured at 15 of 17 cited chunks with `rapidocr`. Version 0 runs keep their IDs.
- *Ownership:* Tri chose; having a scheme matters more than who owns it. Track C builds the stores and loader on it. A lower hit rate on the new chunks (B-F55 item 1) is expected after rechunking and is no reason to change the IDs.

**B-D29 (decision, by Tri; reverses B-D24, which Claude made under delegation). This is D-55.** The per-well fact graph is part of the design. Tri did not decide to drop it.

- The system is GraphRAG with two graphs: the per-well fact graph for end-of-well reports and the event graph for daily reports (B-D26), both fed by retrieval routed by well and date (B-D23). Plain RAG is the baseline the graphs are measured against (D-50), and documents describe it that way from now on.
- Validated facts go back into end-of-well answers (`--fact-sheet --strict-facts --sheet-properties 3`), and fact-graph work resumes: coverage, and loading into Neo4j with Track C.
- B-D24's measurements stand: on new lookup questions the fact graph ties retrieval (E23 29 and 29; E26 23 and 23) at 2.48 LLM calls per page. They show that our lookup questions do not need it. Questions across wells, which the expert set should bring, are where it is expected to help (B-F29).
- Current documents no longer call the fact graph optional, and D-51 is marked replaced. Historical records (E28, E29, the old supervisor request) keep their wording.

**B-F56 (finding; answers B-F55 item 2).** The K1 package is kept out of the repository by design. Khai shared it as a zip on 9 November, after Hung asked for it for the dry-run loader, and did not commit it because data pushed to git is hard to remove. Two points to confirm with Khai: his message gives 1,042 chunks where E30 gives 1,040, and IDs as `docid:s1:c0` where E30 and the code write `<file_id>:s1:c0` with a file ID from the PDF hash (D-54).

**B-C30 (design choice; from B-F56).** Track B runs read a K1 package from outside the repository: `--pool k1_ak3` (the end-of-well report) and `--pool k1_daily` (the four daily-report attachments) load `data/interim/k1/chunks.jsonl`, or the file `GRAPHRAG_K1_CHUNKS` names, and stop with a clear message when it is missing.

- The prototype gold's chunk IDs are old IDs, so retrieval hit flags on these pools mean nothing until they go through the legacy map. Answers are scored by value and are unaffected.
- E28's event graph still reads the old appendix tables and needs a K1 loader to run on the package.

**B-F57 (finding; from Track C's C-F04 and C-F05).** Hung loaded Khai's AK-3 package into Track C's PostgreSQL: 1,042 chunks, all 174 pages rebuilt from the database. His questions to Khai that matter for Track B:

- **No legacy ID map in the package** (`legacy_chunk_ids.json`), so retrieval on the package cannot be scored by chunk. Answers are scored by value and are unaffected.
- **Which OCR engine.** E30's map covers 15 of 17 cited chunks with `rapidocr` and 17 of 17 with `easyocr`, so the engine decides how much gold carries over.
- **End-of-well chunks have no well or date field.** Track B does not need one: `WellRouter` reads each document's well names from its text, and only daily reports need a date. Track C can copy the file's well into the vector payload.

**B-D30 (decision, by Tri). This is D-56.** The vector store is pgvector inside the PostgreSQL that holds K1, as Hung proposed (Track C log C-D03, [comparison](../C-storage/vector-store.md)). It adds no service, filters by well and report date in the same query, and is rebuilt from the system of record. BM25 stays alongside it for one-well questions.

**B-D31 (decision, by Tri). This is D-57.** Khai's K1 version 1 proposal (E30) is the team's chunk-package interface, beyond its ID format (D-54): the six `k1_*` schemas, forms as their own record, report date and well on daily-report chunks, and the QA sidecar next to each release. Packages are shared as files. Still asked of Khai: the legacy ID map with each package and the OCR engine used (B-F57).

**B-C31 (design choice).** The project report for the supervisors, 9 November, is [docs/reports/PROJECT_REPORT_2026-11-09.md](../../reports/PROJECT_REPORT_2026-11-09.md), in English with Mermaid diagrams. It describes the system as GraphRAG with two graphs (B-D29) and covers all three tracks, the roadmap and what the team needs from the supervisors. The file is the record; a web copy was shared from Claude.

## 2026-11-09: supervisor meeting

[Digest](../../requirements/supervisor-meeting-2026-11-09.md). Tri's microphone cut out for much of his part, so the transcript keeps little of his answers.

**B-D32 (decision, from the supervisor). This is D-58.** Keep a coordinator that routes each question to retrieval, the per-well fact graph or the event graph. Today's routing (B-D23, B-D26, the event graph's fallback) is its first version; later it treats these as tools among others, with MCP and connectors. How lanes are split or merged waits for the document scope and question types (Q13). Next is detecting the report type from the question, today chosen per run; the event graph's planner can return it in the same call.

**B-D33 (decision, from the supervisor). This is D-60 and D-62.** A simple UI on the connected tracks comes next, ahead of the rest of M2: question, answer, cited source text and retrieved passages, and the source events behind a computed total. The model stays swappable: Qwen3-8B with thinking off is today's choice, not part of the design.

**B-D34 (decision, from the supervisor). This is D-61.** Reasoning about the causes of a drilling problem is a target question type. No question set covers it yet, and AK-3's reports alone likely cannot answer it. The supervisor also asked for the node and relationship logic of both graphs to be stated clearly; the per-well fact graph's LLM step today extracts only the 14 properties of `oil_wells.json`, not K2's relations.

## 2026-11-10: a simple UI

**B-C32 (design choice; from D-60).** `graphrag/ui.py` and `graphrag/ui.html`: a local UI over Track B's answers, standard library only, on 127.0.0.1.

- **Recorded runs:** any run in `graphrag/results/`, with correctness, the path through the pipeline, the cited passage and page, and tokens and time; two runs side by side. Event totals are shown by rerunning the recorded plan on `E28_events.json` with no model call (E28's TRPI question: 8 events, 13 hours).
- **Live:** the same code as the runs. The lane is chosen from the question's words (dates, hours, NPT, activity codes mean daily reports), standing in for D-58's coordinator. End-of-well questions use BM25 routed by well and the strict fact sheet (12 lines per well, no property ranker, so no embedding server); daily questions use the event planner with its fallback. Hosted endpoints are refused, since the pools mix sources.
- Replay works for all 78 recorded runs. A live answer was tested only with a stand-in model; it needs the desktop's llama.cpp.
- Not yet: chunks from Track C's PostgreSQL, the page image beside a citation, answers on Khai's K1 package.

## 2026-11-10: the event graph on K1 version 1

Tri put Track A's package `ak3-k1-v1-candidate` into ignored `data/interim/k1/` on the laptop.

**B-F58 (finding; answers B-F57's questions from the package itself).** This package is E30's (1,040 chunks), not the 1,042-chunk one Track C loaded. It ships `legacy_chunk_ids.json`, and its manifest names the OCR engine, `rapidocr`. Khai's compatibility check passes: every row loads, the four daily reports are found, all 191 tables give rows, and E30's figures hold (15 of 17 gold chunks mapped, BM25 hit@5 0.913). `graphrag` reports no ID-format gaps.

**B-C33 (design choice).** `graphrag/events.py --k1` builds the event graph from the K1 package: daily-report chunks and tables from K1, each page's report date from `context.report_date` instead of `page_dates`, and NPT codes from appx-23, which the package lacks, read from the corpus release or the older export (`npt_report_inputs`). Built from the corpus, nothing changes. `k1_chunks_path` also finds a package unzipped into its own folder under `data/interim/k1/`.

**E31 (experiment).** The event graph on K1: [E31](../../experiments/E31-event-graph-on-k1.md). 161 / 161 events identical to E28 in every field, 160 now linked to K1 chunk IDs; E28's final recorded plans replay 35 / 35 and 23 / 23. No model call; the answer reruns need the desktop.

**B-D35 (decision, by Tri; a request to Track C).** Stop passing data between machines through chat. Track C (Hung) hosts the shared stores (PostgreSQL with pgvector, Neo4j, a file store for K1 packages) on a free cloud tier, such as AWS or Azure through the GitHub Student Developer Pack, with credentials for each teammate, so all three tracks read and write the same data.

- High priority. Track C owns it, since it builds the database side, and adds Tri and Khai once the resources exist.
- Only public data goes there (AK-3, BSEE, GDR reports); private documents stay on local models and machines (specification §10, D-37). Credentials stay out of the repository.

### 12 November 2026

**B-C34 (design choice).** `graphrag/compare_runs.py` turns recorded answer runs into one side-by-side table per question set (gold, each method's answer and result, cost per method), as Markdown and CSV, with no model call. Written for anh Tuấn, who asked for the questions, both methods' answers and the benchmark method. Output: [E28-answers/](../../experiments/E28-answers/README.md); totals match E28 (22/35, 19/23 for the event graph).

## 2026-11-24: design of the second build

Design and documentation, done with Tri before any code. No experiment was run.

**B-F59 (finding; state of the repository on 24 November).** Nothing from Track B or Track C is recorded after 12 November, and there was no supervisor contact after the 9 November meeting. Track A merged a large change on 17 November: table joining across pages, section context, form recognition, label-value repair, page orientation, quarantine and resumable runs, all as options off by default. The transcript Tri brought is the 9 November meeting, and the digest matches it; Tri confirmed there is no newer direction.

**B-D36 (decision, by Tri; details D-58 and B-D32). This is D-64.** The coordinator is a router now, and an agent later in one lane only. One model call frames the question: its kind, the report type and, for a question over time, the event query plan (B-C24's planner with two more fields). Code reads wells and dates, chooses lanes from a fixed table and falls back to passages in a fixed order.

- Each lane (passages, well facts, events) takes the same input and returns the same evidence shape, so it can later be called as a tool or through MCP, as the supervisor described. A multi-step loop is considered only inside the reasoning lane, after a run shows a model of this size manages it.
- *Why:* a fixed router is cheap, repeatable and measurable; a free tool loop on an 8B model is unproven here and not needed for four of the five question kinds.
- *Test before adopting:* the 221 development questions in one pool with no lane given (31 + 40 + 36 + 30 + 26 + 35 + 23), their source sets giving the expected lane. The coordinator must match the hand-routed scores. It adds one model call to end-of-well lookups (1 to 2); event questions stay at 2.
- Not chosen: a tool-calling agent from the start, and rules with no model call.

**B-D37 (decision, by Tri; replaces the order in B-D33). This is D-65.** The application is built now as a FastAPI backend and a React frontend, read path first, instead of first pointing `graphrag/ui.py` at the stores.

- `graphrag` becomes the library the backend imports. `graphrag/ui.py` and `ui.html` stay a developer tool for replaying recorded runs, not the product.
- Every question asked is logged with its lane, answer and any "wrong answer" mark. Shown to domain experts, that log is the route to real questions (Q2, Q13).
- Work is split by data, backend and frontend. Tri takes the frontend as well as the engine (his decision, 24 November); Khai on data and Hung on backend are the plan's proposal, for the team to agree (Q14).
- Not chosen: keeping the standard-library UI, and a thin FastAPI service that only serves today's HTML.

**B-D38 (decision, by Tri; details D-61 and B-D34). This is D-66.** The reasoning lane is designed and probed, not promised. It finds the problem event in the event graph, gathers what surrounds it in code (days before and after, the non-productive report's description, the day's passages, the end-of-well narrative), and answers in two parts, each with citations: causes the reports state, and possible causes.

- About ten questions on AK-3's 28 non-productive events are frozen before any run, scored on the stated cause found and cited, and no unsupported claim stated as fact.
- Nothing inferred is written to the graph.
- *Why a probe:* one well's reports hold no offset wells, formation pressures or lessons-learned reports, so the probe shows the supervisor a concrete answer and what a useful one would need.

**B-C35 (design choice; answers the supervisor's request in B-D34). Proposed as D-67.** The node and relationship model is in [specification §8.5](../../PROJECT_DESIGN.md#85-the-graph-nodes-and-relationships): one graph with two regions joined at `Well` and `Chunk`, plus `Document` nodes linking a well's daily reports to its end-of-well report.

- Event region, as Track C loaded it (C-C11): `Well`, `ReportDay`, `Event`, `ActivityCode`, `NptCode`, with `FROM` to `Chunk`.
- Fact region, proposed: `Fact` nodes (property, value, unit, qualifier, context, source) under `Well`, each with `FROM` to its chunk, and `HoleSection` and `CasingString` from the casing mappings; the fields `graphrag/tables.py` already writes. A fact is a node because a well can have several values for one property, each with its own source.
- K2's other types (`Project`, `Organization`, `Person`, `Rig`, `Formation`) wait until a kind of question needs them (B-D25).
- To agree with Hung, who asked for it (Track C log, "Next").

**B-C36 (design choice; documents brought up to date).**

- Specification 3.4 adds §4.6 (the second build), §8.5, §8.6, D-64 to D-67 and Q14, Q15, and rewrites §8.1 to §8.3 around the coordinator.
- Removed from it: graph expansion by a fixed number of hops and community summaries (§8.1), which no run supported (E16, E19, E21); the vector-store candidates (§4.2), settled by D-56; the claim that the GraphRAG parts are not built (§3.1).
- Plan 3.2 is rewritten around how M1 closed, the M2 checkpoints and one task list by role. A new [tracks index](../README.md) has a pointer for Track A.
- Experiment numbers reserved: E32 answers on K1 version 1, E33 the coordinator on the pooled questions, E34 the reasoning probe.

## 2026-11-24: lanes, coordinator and the fact graph export

Plan tasks E3 to E6, written from the [implementation plan](plan-lanes-and-coordinator.md) on the laptop with stand-in models. **No model was run and nothing was measured**: the laptop has no GPU and no model files. E33 is the measurement, and it needs the desktop.

**B-C37 (design choice; builds B-D36).** `graphrag/lanes.py` puts the three answer paths behind one shape: `lane(question, frame, engine) -> Evidence`.

- `Evidence` carries passages, facts or a computed result (plan, values, unit, events, source chunks), with `exact` true for facts and computed results. `Engine` holds what the lanes read and loads it from files (`Engine.load`); reading the stores replaces only that method.
- The settings are the baseline's (B-D23, B-D26), and no lane calls a model. The well-facts lane hides planned values unless asked (B-C21); its passages are the chunks of the facts a prompt shows, 12 per named well, because one well can have over a hundred survey facts.
- `graphrag/baseline.py` gains `answer_one`, the body of `answer_questions`' loop. A test against recorded hashes shows the 40 requests of two baseline runs are byte for byte unchanged, so the request cache and E14 to E31 still reproduce.

**B-C38 (design choice; builds B-D36).** `graphrag/coordinator.py`, the coordinator of specification §8.1.

- **Frame.** One call with `FRAME_SCHEMA`: `kind` and `report_type` first, then the event planner's fields (B-C24), so the plan is written knowing whether the question is over time (B-F22's field-order lesson). The prompt is the planner's plus definitions of six kinds and four report types.
- **Code decides.** A frame outside its lists becomes the empty frame, which routes to the end-of-well lanes. One well read in the question replaces the plan's well; two or more make the kind `across_wells`.
- **Route.** Over time with a plan: `events`; daily reports: `passages`; else `well_facts` then `passages`. If nothing is found, passages run on the daily or end-of-well reports as the question suggests. `exact` mode drops `passages` and, with nothing in the graphs, returns `not_found_in_graph` with no answer call and the closest passages as sources.
- **Answer.** With facts and passages both found, the prompt is what E22 and E26 measured: the fact sheet before the passages, with facts' chunks not added. `--no-embeddings` uses per-well BM25 for several wells.

**B-C39 (design choice; task E6, changes specification §8.1 and §8.3).** A result computed by code is the answer as code wrote it, with no second model call.

- `graphrag.events.plan_value` returns a plan's result as values and a unit beside the text. `run_plan` wraps it with its text unchanged, because Track C replays 58 recorded plans against that text.
- The answer row takes its values from code and cites the source events (`how: event_graph`).
- A computed answer costs one model call (the frame), where E28 spent two. The two-call path scored 19 of 23 on E28's new set; E28 estimated 22 from the rows for reporting in code, computed and not run. E33 is to show what it gives.
- *Why:* the specification had the model word a sentence around the number, but the result text is already a sentence, and one call fewer is cheaper.

**B-C40 (design choice; builds B-C35, D-67).** `graphrag/factgraph.py` writes the fact region as nodes and relationships for Track C's loader: `python -m graphrag.factgraph --facts <fact runs> --name <name>`.

- Nodes `{label, key, properties}`: `Well`, `Document`, `Chunk`, `Fact`, `CasingString`, `HoleSection`. Relationships `{type, from, to}`: `HAS_FACT`, `FROM`, `DESCRIBED_BY`, `HAS_CHUNK`, `HAS_CASING`, `HAS_SECTION`. Sorted and without duplicates, so the same facts give the same file.
- Facts pass `graphrag/validate.py`'s strict checks first; a fact's `source` is `table_mapping` or `llm`. A casing string takes its depth, weight and grade from actual facts only.
- `CASED_WITH` is not written, because no fact says which casing was set in which hole; specification §8.5 now says `HAS_CASING` from the well.
- First export, [`E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json), from `E20_graph_three_qwen3-4b` and `E27_tables_three`: 892 facts read, 216 kept; 5 wells, 3 documents, 38 chunks, 11 casing strings, no hole section; no dangling relationship.

**B-F60 (finding; from the first export, B-C40).** Two things to check before the fact region is trusted:

- **Offset wells.** 13 facts, all from LLM extraction and none checked against gold, are about TG-2 and TG-4, earlier Akutan wells the AK-3 report describes. Their document is rightly the AK-3 report, but a question about "the well" of that report must not pick them up.
- **A casing string that may be a hole size.** 68-32 has a casing string of size `8-3/4`, which reads like a bit size. Not checked against the report.

**B-C41 (design choice).** K4 version 0.2, for coordinator runs only: `pipeline` gains `lanes`, `mode` and `frame_kind` with `base: "coordinator"`; `models` gains `frame`; `status` gains `not_found_in_graph`; `cost` adds the framing call to the answer call. Earlier runs still write 0.1. Model roles (`frame`, `answer`, `extract`, `embed`) are in `configs/graphrag/roles.json` (D-62), read by `client.client_for`.

**B-C42 (design choice).** The local UI's live answers go through the coordinator (`ui.ask(question, lane, mode)`); its own lane guess (`choose_lane`) and fact sheet are removed. The page is unchanged and lacks the exact-answer switch, which belongs to the React application. Pooled coordinator runs are not listed for replay.

**Not done, and why.** E32 and E33 need Qwen3-8B on the desktop GPU. The command for E33:

```powershell
python -m graphrag.coordinator answer --questions prototype simulated heldout ak3_daily ak3_daily_heldout ak3_events ak3_events_heldout --name E33_coordinator_pool
```

The daily-report corpus is not on the laptop either, so the daily and event lanes were tested on stand-in chunks and events only.

## 2026-11-24: review of the lanes and the coordinator

An independent read-only review of the day's code confirmed the two hard constraints by running them: `run_plan` gives the same text and events on all 154 plans recorded in `graphrag/results/`, and the baseline's requests are unchanged. It found eight defects, all fixed the same day, each with a test that failed first.

**B-F61 (finding; from replaying E28's recorded plans, no model call).** With the result reported by code (B-C39), E28's plans score **33 of 35** on the seen set, where the two-call path scored 27 (`E28_graph_fixed_seen`), and **22 of 23** on the new set, where it scored 19 (`E28_heldout_graph`). The 22 matches E28's unrun estimate.

- Nine answers go from wrong to right (t04, t13, t14, t23, t25, t30, g07, g11, g13); each had a right computed result that the answer call garbled or abstained on.
- Not a new run: the plans are E28's, and the coordinator's framing prompt adds two fields and may write different plans. E33 is the measurement.
- Kept as a test (`RecordedPlanTests`), so a change to the event lane that loses these answers fails.

**B-C43 (design choice; fixes from the review).**

- **Modes.** `exact` drops passages from a forced lane too (the UI's "end-of-well" choice answered from passages). Well-facts passages are 12 per well, as B-C37 said, instead of 12 times the number of wells.
- **Wells and frames.** A name counts as a well only if the engine holds it (`Engine.wells`), because the pattern also matched "20-22 August" and "BHA-2", and a right plan fell back to "not stated". A frame with wrongly typed plan fields becomes the empty frame, since a hosted endpoint may not enforce the schema as llama.cpp does.
- **Rows and runs.** Rows without an answer call carry every key `answer_one` gives, so `baseline.summarize` reads them. `Engine.has_daily` stops a pooled run without daily reports, and each row's `answered_from` names the reports behind its evidence. The UI uses per-well BM25 without the embedding server; `compare_runs` and the replay refuse pooled runs with a reason.
- **A test that could not fail.** `test_run_plan_text_is_unchanged` compared a function with itself; it now asserts the text of ten operations and replays the 23 plans of `E28_heldout_graph`.

**Left open from the review** (small; none changes an answer today):

- `factgraph`: facts equal in well, property, qualifier, context and value merge with the last `source` and `unit` winning, and two actual casing values for one size would overwrite each other (no such pair in today's 216 facts). `DESCRIBED_BY` links TG-2 and TG-4 to the AK-3 report (B-F60).
- A question over time about 56-32, which has no daily reports, falls back to AK-3's daily passages, as the baseline does.
- `ui.html` hides lanes, mode and frame and shows `not_found_in_graph` as "not stated"; the React application replaces it.
- K4 0.2 writes `cost_usd` 0 for every coordinator row, also on a hosted endpoint; K4 for a daily set needs the daily corpus; the retriever cache and UI engine are shared across threads without a lock; no test runs `main`.

## 2026-11-24: Hung's agreement, and backend work on his behalf

**B-D39 (decision, by Hung, told to Tri and relayed to Claude by Tri on 24 November).** Hung agrees with the design of the second build, including the graph model (D-67) and his role on backend and stores (Q14). He asked whether part of his work could be done for him for now, and Tri agreed.

- **Done on his behalf:** the read-path API, its contract and the question log (plan tasks B4, B5, B6), because the frontend, which is Tri's, cannot start without them (B-C44).
- **Designed for him in [backend-design.md](../C-storage/backend-design.md), not built**, because they need stores or accounts only he has: shared hosting (B1), the runner (B2), loading the fact region into Neo4j and the event region on K1 version 1 IDs (B3), page images (B7), the compose file with the access gate (B8), and the question log in PostgreSQL.
- Khai agreed to the data role the same day (B-D40).
- *Why recorded here:* the agreement reached Claude through Tri, and the Track C log is Hung's; a short entry there points back to this one.

**B-C44 (design choice; plan tasks B4, B5, B6, done on Hung's behalf under B-D39).** `backend/`, the read-path API of specification §7.5, as a FastAPI service. `create_app(service)` takes the service, so tests pass a small engine and stand-in models. FastAPI 0.165.0 and uvicorn 0.54.0 are pinned in `backend/requirements.txt`, apart from the main lock file, so ingestion environments need no web framework.

- **Endpoints** under `/v1`: questions and their feedback, chunks, files and their pages, wells and their events, health. An answer carries the lanes, the frame, any fallback, the reports that answered, citations with text and page, the evidence shown (rows gained `shown_passages` and `shown_facts`), the checks and the cost.
- **The contract** (`backend/openapi.json` and ten examples in `backend/fixtures/`) is generated from the code, and a test fails when it falls behind. The examples' evidence is real; their model is a stand-in scripted in `contract.py`.
- **Reads files, not the stores** (`GET /v1/health` says `"source": "files"`). The question log is a JSON-lines file under ignored `data/interim/backend/`, not committed because it holds what users typed. An unknown ID gives 404, a bad body 422, a silent model server 503 with a message; one question runs at a time.
- **Checked without a model:** "How many hours of non-productive time did AK-3 have?" computes 115 hours from 28 events on 10 dates, the figure of the report's own time table (115.0) and of Track C's count in Neo4j (C-F06). 17 tests (`tests/test_backend.py`), skipped without FastAPI.

**B-D40 (decision, by Khai, told to Tri and relayed to Claude by Tri on 24 November).** Khai is fine with the data role for the second build: PDFs to K1 packages, table and form quality, the QA sidecar and new reports ([plan §2](../../DEVELOPMENT_PLAN.md#2-team-split)). With B-D39 the roles for this stint are settled: Khai data, Hung backend and stores, Tri the engine and the frontend. Khai is asked first for the demo release (plan task D1). The agreement recorded is to the role; whether he has read the design is not known.

## 2026-11-24: the frontend

**B-C45 (design choice; plan tasks F1 to F4; look and wording replaced by B-C47).** `frontend/`, the React application (React 19, TypeScript 5.9, Vite 8), built on `backend/openapi.json` and the example responses. Not run against a real model.

- **Screen.** The answer on the left (value, source, the three steps with model calls and seconds, right or wrong) and the evidence on the right: a 24-hour strip per report day with non-productive time hatched for a computed number, or the passages read with the value marked (`1955` finds `1,955`) and the checked facts.
- **Words and type.** Every sentence is in `src/lib/wording.ts`, none naming a lane or a frame. Report text is serif and the application's words sans; amber is kept for non-productive time and warnings.
- **Behaviour.** The graph-answers-only switch (D-59), a seconds counter while waiting, earlier questions folded, a link carrying a question (`?q=`), light and dark by system setting. Types come from the contract (`npm run types`); TypeScript is pinned to 5, because the generator does not run on 7.
- **Examples mode** (`npm run dev:examples`) serves the committed responses with no server or model, and says so on screen. 41 tests (`npm test`). Not done: the page image, report titles, login.

**B-C46 (design choice; speed).** Responses over 2 kB are compressed (an answer with its evidence is tens of kilobytes); the browser may keep reads for a minute and answers never; the question log keeps logged IDs in memory; the engine builds its chunk index once. The frontend loads example responses on demand, bundles its fonts so no outside request is made, and does not redraw the answer while the question box changes. None of this was timed, because the model's calls dominate and no model ran.

**B-F62 (finding; seen in the application's "Checked facts" table).** AK-3 has a validated fact `spud_to_release_days = 3`, read by the model, while the passage beside it says "a total of 19 days". It passes because a 3 is written in its chunk: the value-in-chunk check cannot catch a small number that occurs for another reason. A wrong fact reaches the answer model, one more reason to settle B-F60's doubts before the fact region is trusted. The application showed it at once; it had not been noticed in the result files.

**B-C47 (design choice; from Tri's reaction to the first screens: "the user is not a dev").** The frontend is redone for non-developers, replacing B-C45's look and wording; its behaviour and structure stay. The first version came up dark and technical on Tri's machine and spoke the system's language ("graph answers only", "operations", "1 model call").

- **Look.** Always light, with one blue for things to press and Plus Jakarta Sans; report text stays serif. The dark theme is removed.
- **Words.** "Graph answers only" is "Verified data only", "operations" are "activities", and reports are named as a person would ("AK-3 end-of-well report, page 7"). A test fails if the application says lane, frame, graph, chunk, token, model call, fallback or coordinator. Each answer has a trust label: calculated from the reports; written by AI and checked; written by AI and not confirmed; no answer found.
- **Help.** An "i" beside each term (`Tip.tsx`) and a first-visit guide with example questions (`Guide.tsx`). Each report is listed once. The technical trail and cost fold under "How we got this answer".
- 49 tests, with checks from two installed design skills (contrast, 40-pixel targets, visible focus, reduced motion). Not run against a real model, and no domain expert has seen it, so whether it is intuitive for them is unknown.

## 2026-11-24: stint report and notes to teammates

**B-C48 (design choice; documents; partly revised by B-C49).**

- **Stint reports have their own folder**, `docs/reports/stints/`, one per stint, as Tri asked. The [report for 10 to 24 November](../../reports/stints/STINT_REPORT_2026-11-27.md) is written for anh Tuấn in the shape he asked for on 9 November: what he asked and where each stands, one picture, one question walked through, weak points, what we need. Tri's 5 November update moved there as `STINT_UPDATE_2026-11-05.md`.
- **Requests to teammates are dated notes in their track folders:** [for Khai](../A-ingestion/note-from-track-B-2026-11-24.md) (the demo K1 release with appendix 23, the legacy ID map and a well on end-of-well chunks first) and [for Hung](../C-storage/note-from-track-B-2026-11-24.md) (what was done on his behalf, his tasks in order with shared hosting first, four decisions that are his).
- The first version of the report also said that most work happened on 24 November and that there was no supervisor contact after 9 November; B-C49 removed that.

**B-C49 (design choice; the stint report as a draft with diagrams, and the root folder cleared).** From Tri's review of B-C48's first version.

- **The stint runs to 27 November**, so the report is `STINT_REPORT_2026-11-27.md`, a draft until then. At Tri's request it no longer remarks on when the work was done or on supervisor contact: a stint report says what was built and what is weak.
- **It explains the system** in diagrams (the four parts and their owners, a question's path, the knowledge graph) and three screenshots, and says what each person built; the backend is Tri's and Hung's work together.
- **Generated:** `scripts/stint_figures.py` draws three plain SVG files, because Mermaid came out too small on a page (it stays the rule for the specification). `scripts/render_stint_report.py` prints the Markdown source to a PDF committed beside it. The notes to Khai and Hung became work lists.
- **Moved out of the root:** the professor's review slides to `docs/reports/slides/ARCHITECTURE_TODAY_2026-11-12.pdf`, the 27 October report's PDF to `docs/reports/`, and `KGinEP.docx` to the ignored `docs/requirements/originals/KGinEP-en.docx`.

## 2026-11-24: building all three tracks toward production

**B-D41 (decision; build everything that needs no key, server or GPU, in all three tracks).** Tri, with Khai's and Hung's clearance, asked for all work possible without new resources to be done now, in whichever track, so that what is left at the end of the stint is to rent the server, set passwords and keys, and run the measurements that need the desktop GPU.

- **How:** one plan with fixed interfaces and one work package per development agent, each in its own git worktree, so no two touch the same file: [plan-production-readiness.md](plan-production-readiness.md). Tri's session (Claude) wrote the plan, reviewed and merged each package, fixed what the packages found in each other, and ran the whole application end to end.
- **The agents are coding helpers only:** Claude models on a separate API key. The pipeline still calls only open-weight models, and no agent wrote evaluation data. The reasoning probe's questions were written in Tri's session and are marked simulated (B-D22).
- **Cost:** about US$27 for the five packages merged at that point; the full breakdown is in B-F65.
- **Nothing here is measured with a real model.** Every number below comes from tests with stand-in models or from loading and reading data.

**B-C50 (design choice; the engine and the backend read the stores).** Plan tasks E2 and B6; backend design §3 and §5.

- **`graphrag/stores.py`** builds from PostgreSQL and Neo4j the same `Engine` that `Engine.load` builds from files, and `import graphrag` still needs only `httpx` and `numpy`. On Khai's K1 candidate (1,040 chunks), the chunks, E31's 161 events and the facts read back identical.
- **Switch by environment:** `BACKEND_SOURCE=stores` with `BACKEND_DSN` and the `NEO4J_*` variables; `GET /v1/health` reports the source. A configured store that is unreachable stops the server at start instead of answering from files. `GRAPHRAG_ENDPOINTS` and `GRAPHRAG_ROLES` point a deployment at its own model server.
- **The question log in PostgreSQL** (`PostgresQuestionLog`, `platform/sql/002_questions.sql`) passes the file log's 19 tests; `python -m backend.questions counts` gives questions by kind, answered and marked wrong.
- **Not built: vector search in SQL.** `baseline.build` makes retrievers over chunks in memory, so a pgvector retriever does not plug in cleanly; questions naming several wells use the in-memory retriever. To do when the vectors exist on the shared store.

**B-F63 (finding; exact mode crashed on the stores).** With the stores as the source, an exact-mode lookup raised `KeyError` in `baseline.answer_one` (a 500 through the API).

- **Cause:** E27's facts cite K1 version 0 chunk IDs (`gdr882_ak3_eowr#c0008`), and none of their 38 chunks is in the K1 version 1 release the engine holds. Normal mode hid it, because passages came from retrieval.
- **Fix:** the coordinator shows only passages the engine holds; the fact still counts, without its passage. A test covers it.
- **What it means:** on the stores, facts and passages are not yet on one ID scheme, and the legacy map cannot bridge it: 26 of the 38 chunks belong to the two other end-of-well reports, which are not in the release. It closes when the demo release holds the three reports and the facts are rebuilt on it (plan tasks D1, D3; backend design §4.2).

**B-C51 (design choice; the reasoning lane).** Plan task E7, specification §8.6: `graphrag/reasoning.py`, a fourth lane.

- **Find the problem, in code.** Non-productive events with one code on consecutive days make one incident: AK-3's 28 events make 6 incidents, 115 hours. The frame gains a `problem` (date, depth, non-productive code, up to three keywords), and its kind `reasoning` is renamed `cause`; the framing prompt grew by 497 characters and `max_tokens` from 260 to 320, which no recorded run depends on (E33 is unmeasured). Several matches: the answer lists them and asks which, with no answer call. None: the fixed fallback to passages.
- **Gather, in code.** The incident's events, the days before and after, three passages of those days' reports and three end-of-well passages: at most about 13,200 characters (3,300 tokens). A question costs at most about 4,500 tokens with a 900-token answer, twice an end-of-well lookup.
- **Answer and check.** One call under a JSON schema gives `stated` (causes a report gives) and `possible` (factors visible in the evidence), each with citations. Code removes and counts items citing evidence not shown; exact mode hides `possible` and says how many. "What is missing" lists the four kinds of evidence §8.6 says this corpus lacks, plus up to five the model adds. K4 version 0.3 carries the `reasoning` object and the status `ask_which`; 0.1 and 0.2 still validate.
- **Open, for the specification:** exact mode still runs the lane, though its stated causes rest on passages and the model's reading, and D-59 says exact mode uses exact evidence only. To decide with the supervisor's "verified data only" in mind.

**B-C52 (design choice; the reasoning probe's questions, frozen).** [`graphrag/gold/ak3_reasoning_probe_v0.json`](../../../graphrag/gold/ak3_reasoning_probe_v0.json): ten questions on AK-3's non-productive events, frozen before any run with a real model, for E34.

- Eight name one problem with a cause the event descriptions state (plugged inner barrel, the foot clamp slipping, failed generators, weather, waiting on the well design); one names none, where asking "which problem?" is right; one names a problem that did not happen.
- **Simulated, not expert-reviewed**, written in Tri's session from the recorded events. Limits in the file: causes stated elsewhere in a report count as unsupported and must be read by hand; terms match as text; chunk IDs are left open so the probe runs on either ID scheme.
- **Run:** `python -m graphrag.coordinator answer --questions graphrag/gold/ak3_reasoning_probe_v0.json --name E34_reasoning_probe`, on the desktop.

**B-C53 (design choice; the API and the page view).** Plan tasks B7 and F2, and the contract for the reasoning lane.

- **Contract:** the lane `reasoning`, the status `ask_which`, the kind `cause`, `frame.problem` and `evidence.reasoning`, with two new examples (`question_cause.json`, `question_cause_which.json`).
- **Page images:** `platform/render_pages.py` writes one PNG per page with `pypdfium2` at 150 dpi (AK-3's end-of-well report: 29 pages, 13 MB, 21 s; a second run skips them all). `GET /v1/files/{file_id}/pages/{n}/image` serves one, checking the file ID against the engine's files and the page as a positive integer before any path is built.
- **Frontend:** a source opens on "Page as printed" with the cited passage beside the image. The production build calls `/v1` on its own origin and has plain messages, with "Try again", for a rejected password, a proxy error, and a slow or unreachable server.
- Not checked in a browser by the agent; no highlight on the image, because K1 passages carry no region.

**B-C54 (design choice; the whole application run end to end on this laptop).** After merging, `docker compose --profile app --profile demo up -d --build`, with `BACKEND_SOURCE=stores`, the stub model in place of llama.cpp, and the proxy on port 8088.

| Check | Result |
|---|---|
| The gate | A request without the password is refused (401) |
| The frontend through the proxy | Loads |
| Health | `"source": "stores"`: 61 end-of-well chunks, 979 daily chunks, 161 events, 216 facts, 5 wells |
| Questions | Seven asked through the proxy in both modes, and each lane forced once: all answered with status 200 |
| The question log | Each question is a row in PostgreSQL's `questions`; feedback is a row in `question_feedback` |
| `deploy/smoke_test.py` | 5 of 5 checks pass |

- **The stub is not a model.** Its answers start with "[stub model]" and it frames every question as a lookup, so this run proves the wiring and no answer. Tests with stand-in models cover the lanes.
- **Tests after merging:** engine 196 (4 skipped), backend 56, the platform and stub suites, and the line-ending test, all passing.

**B-C55 (design choice; the demo K1 release, built here with Khai's clearance).** Plan tasks D1, D4, D5. Khai has not reviewed it; the release and the draft [Track A log](../A-ingestion/log.md), written from the repository's history, are his to correct.

- **`python scripts/build_k1_demo_release.py`** builds the release from AK-3's end-of-well report, appendices 27 to 30 and appendix 23: 6 files, 176 pages, 1,051 chunks, 197 tables, 81 forms. It reuses the E8 corpus's Docling output for the appendices and converts only the end-of-well report again. Not committed (`data/interim/k1/ak3-demo-v1/`).
- **The five checks of the [note to Khai](../A-ingestion/note-from-track-B-2026-11-24.md) pass:** the validator, with the same `SHA256SUMS` on a second export; 981 of 981 daily chunks carry a date and a well; the event graph from the release alone has 161 events and no old-style ID; the legacy map is inside (60 entries, 15 of the 17 gold chunks, as E30 found with this OCR engine); 61 of 61 end-of-well chunks carry `AK-3`.
- **A well on end-of-well chunks** comes from a new optional K1 setting, `document_context`, off by default, which puts the cover page's well on every chunk (`context.well` already existed). `graphrag/events.py` reads appendix 23 from the release when it holds it, so `python -m graphrag.events build --k1` needs nothing outside the package.
- **Merged-cell text (D4):** the fix already existed as the table Markdown mode `span_once_keyed`, now shown by a test. On this release it changes 11 table chunks and no ID, and removes the two high character-ratio warnings. Switching it on is Khai's decision (D2). The two tests that failed without PyMuPDF now skip with a reason.

**B-F64 (finding; the demo release changes the wording of 31 events, and nothing else).** The 161 events from the demo release equal E28's in date, time, hours, depth and code. 31 differ in the description only (for example "weather Delay" for "Weather Delay"), because the release was built with today's `k1.json`, which rebuilds the Operations Summary tables, and Khai's candidate was not. The 58 recorded plans still replay. Whether the rebuilt text is better is part of Khai's D2.

**B-C56 (design choice; the demo release in the stores, and a runner option it needed).** `python platform/run_release.py data/interim/k1/ak3-demo-v1 --skip-vectors --replaces ak3-k1-v1-candidate`, then again without `--replaces`.

- **Result:** 1,051 chunks, 176 of 176 pages rebuilt from the database, 161 events on 27 days, 58 of 58 plans, 216 of 216 facts; the second run reports the same. **All 94 chunks the events cite are K1 version 1 IDs and all are in PostgreSQL**, where the candidate left the 28 non-productive events on old IDs.
- **`--replaces <release>`** is new: in Hung's tables a file belongs to one release, so a newer release of the same reports cannot load beside the older one, which is removed in the same transaction as the load.
- **Still on old IDs:** the fact region (B-F63).

**B-C57 (design choice; the frontend shows an answer about a cause).** `frontend/src/components/Cause.tsx`, `CauseEvidence.tsx`, `lib/cause.ts`; 91 frontend tests.

- **The answer in parts:** the problem found; "What the reports say caused it", with the report's words and sources; "Other possible factors (not stated in any report)" in a dashed box marked "Possibility, not a finding", hidden and counted under "Verified data only"; "What a real judgement would still need".
- **Several problems fit:** they are listed as choices, and choosing one asks again with that problem's date.
- **Seen in a browser** (example mode, headless Edge): both screens are in the [stint report](../../reports/stints/STINT_REPORT_2026-11-27.md).
- **Known limits:** surrounding activities arrive as text lines the frontend parses back into rows, so a structured activity in the contract would be sturdier; two problems starting on the same day cannot be told apart when asked again; a daily-report citation has no page to open.

**B-F65 (finding; what building with several agents cost and showed).**

- **Cost:** about US$50 on the separate API key for seven packages (stores 3.05 and one cut-off run of unknown cost; engine on the stores 4.78; deployment 8.55; reasoning lane 9.22; page images 1.76; data 13.76; the cause screens 4.21).
- **Six agents at once ran this 16 GB laptop out of memory:** one never started and one was cut off without a report, though its files were intact and a second agent finished from them. Five at once held. Fixed interfaces written first kept merges small: one conflict, in `backend/app.py`, which two packages were told they shared.
- **The same work was done twice:** Hung wrote a fact loader, the password rule, a backup script and a server guide the same afternoon; each overlap was settled on what the version does (Track C log, 24 November, later). Lesson: say in the group chat what is being built before building in a teammate's track, even with clearance.
- **What no agent could do:** look at a screen, run a model, or notice that the store already held the same files under another release name. Running the whole thing found those.

## 2026-11-24: compute and the resource request

**B-D42 (decision; the desktop is borrowed and hosts nothing for the team).** Tri's answer to Hung's proposal (Track C log C-D06, C-D07): the desktop with the GPU is a borrowed machine. It cannot host the stores over Tailscale, and it cannot serve the demo's model to others. Hosting is Hung's machine or a rented server.

**B-D43 to B-D46 and B-C58 (same day; folded into B-D47).** Five versions of one decision, made within hours as Tri gave more information: first a hosted model or the school GPUs (B-D43, B-C58); then rented cloud compute instead of school hardware, at about US$1,000 for six months (B-D44); then a ceiling of 10 million VND (B-D45); then three months at 7.5 million (B-D46). What they established is in B-D47.

**B-D47 (decision; compute is rented, and 5 million VND is asked from the capstone funding).** Tri, 24 November. Project decision D-68.

- **Why rented:** the team has no GPU or server of its own. Anh Tuấn advised that the school's machines are slow and awkward. A Claude key cannot stand in: only open-weight models of about 8B that we run are allowed (D-37), and a score from another model would not measure this system.
- **What is rented, on public data only:**
  - a cloud GPU by the hour, running our own 4-bit copy of the model with llama.cpp, so scores stay comparable with the recorded ones;
  - a small server for the stores and the application;
  - a hosted open-weight model for the demo and quick checks. A hosted score is compared only with a baseline rerun on the same endpoint.
- **The request:** 5 million VND (about US$190 at an assumed 26,000 VND to the dollar) for December 2026 to February 2027; the rest is for next semester. A 24 GB GPU for about 10 hours a week (1.2 to 2.3 million), a server of 4 vCPU and 8 GB (0.8 to 1.2 million), 0.5 million of hosted calls, a domain name and a reserve. Estimated 3.3 to 4.8 million. Detail and the email: [resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md).
- **Who is asked:** anh Trường, by email, copied to both advisors. Dr. Le Duy Dung's words, as Tri passed them on: "nếu cần tài nguyên thì email anh Trường để sử dụng funding cho capstone nhé".
- **Unverified:** nothing hosted or rented has been run. The GPU hours are estimates from the borrowed card. The model ID `qwen/qwen3-8b` at OpenRouter, and whether thinking can be turned off there, are unknown until the first call.
- **A limit that got sharper:** every rented machine is someone else's. A private VPI document can go on none of them without VPI's written agreement, and the team now has no machine of its own to process one.

**B-C59 (design choice; the documents reorganised to be read).** Tri asked for documents a person can read: concise, no repetition, not a log.

- **One home for each kind of fact**, written into [docs/README.md](../../README.md): design and decisions in the specification, status and tasks in the plan, numbers in experiment records, history in the track logs, how to run something next to the code.
- **Root README:** from 155 lines to about 75, with the architecture picture. Removed from it, because they live elsewhere: the component status table (plan, current status), the ingestion, import and reproduction commands (the [component guides](../../components/)), the folder-by-folder layout (a short table now), and the workflow notes that no longer matched practice.
- **Plan:** the status section is one paragraph and two short tables; the task list (§7) has a State and a Left column in place of paragraphs of history, and starts with what each person does next.
- **CLAUDE.md:** from 170 lines to about 105. Removed: the copy of the results table (the experiment register owns it), the module table (the engine README owns it), the history of the next-steps list.
- **This log:** a short current-state table, a contents table by date, and the day's five resource decisions folded into B-D47. Earlier entries are unchanged.
- **Not reorganised:** the specification (1,400 lines), which needs its own pass, and the Track A and Track C logs, which are their owners'.

## 2026-11-25: everything that needs no compute

Tri asked for every piece of code that can be written without a model or a budget. Built by development agents on the separate API key, each in its own worktree, reviewed and merged in Tri's session; about US$45 in all. Every result below comes from stand-in models or from loading and reading data, except B-F67.

**B-D48 (decision; no gateway library and no outside evaluation tool).** Swapping and testing models needs three layers: a server that runs a model, one way in that hides which server it is, and an evaluation that compares candidates. The project has the first two (llama.cpp, and a client that speaks the OpenAI API to any address, with OpenRouter as the hosted way in). The third was missing and is built here (B-C60).

- LiteLLM is not added: it would duplicate the client.
- promptfoo and similar tools are not added: they compare prompts and outputs, and our scores come from our own pipeline (the coordinator, retrieval, citation and value checks in code).
- vLLM, Ollama and LM Studio need no code: each speaks the OpenAI API, so each is a profile. Their model copies differ from ours, so their scores are compared only with a baseline rerun on the same profile.

**B-C60 (design choice; model profiles and the bench).** `graphrag/bench.py`, `configs/graphrag/models/`, 33 tests against the stub server.

- **A profile** is one JSON file: one model on one address, how thinking is turned off there, the context it needs, optional prices. Code takes a profile wherever it takes an endpoint name. A profile's calls are cached apart from every other profile's, so a resumed run never reuses another model's answers.
- **`bench check <profile>`** sends three calls and reports whether the model is usable: the endpoint answers, the model ID exists, the server runs the named model file, JSON-schema output is honoured for the framing and answer schemas, thinking is off, a reasoning-size prompt fits, tokens are reported.
- **`bench run <profile> --suite quick|full`** runs the existing commands one request at a time: the hand-routed baselines, the coordinator on the 221 pooled questions (E33), every step on the K1 package (E32), the reasoning probe (E34). It resumes after an interruption at no new cost, and records the profile, the server's settings and totals of calls, tokens, seconds and cost.
- **`bench compare`** puts runs in one table and refuses to line up runs of different profiles as if they were comparable.
- **`scripts/experiment_record.py`** drafts an experiment record from finished runs, with the tables filled and the prose left blank for a person.
- **`scripts/setup_gpu_box.sh`** sets up a rented Linux GPU machine. Never run; its syntax is checked. Its llama.cpp and uv versions are unverified.
- **[next-runs.md](next-runs.md) is rewritten around these commands.** Removed from it: the history of E23 to E29, whose records are in `docs/experiments/`, and the "waiting on" table. Two of that table's items have no other home and stay open: `DateRouter` still guesses a page's date from its text and should read K1's report date; the full suite has never run end to end.
- **First named "the model socket"; renamed.** It is a bench.

**B-C61 (design choice; vector search inside PostgreSQL).** `graphrag/retrieval.py` gains a `PgVector` retriever, and `build` a `pgvector:<model>` spec that works wherever `dense:<model>` does.

- **Equal to the in-memory search:** 475 searches return the same chunks in the same order from SQL as from `Dense`, on hand-made vectors, across 19 questions, every k and five filters. About 17 ms a search over 1,042 vectors and 80 ms over 10,000, on random vectors.
- **Chosen once, when the engine is built from the stores:** the SQL search when every chunk of the release has a vector and the embedding server answers; per-well BM25 otherwise, with a warning that names the counts. `GET /v1/health` shows the choice and the number of vectors.
- **`Dense` now breaks exact ties by reading order.** It used to depend on an unstable sort. Only identical passage texts tie exactly; no recorded hash changed.
- **Not run on real vectors:** the laptop's store has none.

**B-F66 (finding; a well name just before a full stop is not recognised).** In "…AK-3 and TG-2." only AK-3 is found, so the question is not treated as naming several wells. Found while building B-C61. Left as it is: changing the pattern changes the recorded request hashes, so it is a deliberate change to make with a rerun, not a side effect.

**B-C62 (design choice; the backend's read side for people).** `backend/`, 79 tests against the file log and PostgreSQL.

- **Activities in cause answers are structured.** Each event among the reasoning lane's evidence carries its fields beside its text line. The prompt the model sees is byte-identical. The frontend no longer reads fields back out of text.
- **The question log can be read and exported** (D-65): `GET /v1/admin/questions` with filters and paging, one question with its stored record, counts by kind, status and mark, and an export as a question-set file the coordinator can run, with empty gold for a person to fill. Read-only. No login: the application sits behind one shared password.
- **The log keeps what each answer's trust label rested on** (the checks, and whether code computed it), so a logged answer can be shown later as it was shown then.
- **A well page's data** in `GET /v1/wells/{id}`: facts grouped, each with its report and page; documents; report days with hours and non-productive hours; totals. On the committed data AK-3's non-productive total is 115.0 hours, which is the report's printed total.
- **A store that drops while a question is answered** gives a 503, as a model that does not answer does.

**B-C63 (design choice; three screens).** `frontend/`, 140 tests; seen in headless Edge at desktop and phone widths.

- **A page per well:** what we know, in plain names with units; planned beside actual casing; the days as the existing timeline; the reports. Each value opens its page.
- **"Questions people asked":** counts, a list with filters in plain words, an opened question with its marks and comments, and "Download these as a question set". For the team and the advisors; it changes nothing.
- **The page view was checked in a browser** and works at both widths. One flaw found and fixed: the example answer cited page 7 and the example page shown was page 2.
- **Visible on the well page, and wrong:** "Days from spud to rig release: 3 days" for AK-3 (B-F62). The page shows the data as it is; the fact is still to correct.

**B-C64 (design choice; three reports in the package, and the facts on its chunk IDs).** Plan tasks D3 and B3, with Khai's clearance. Closes most of B-F63.

- **`demo-v2`:** the end-of-well reports of AK-3, 56-32 and 68-32, AK-3's four daily-report attachments and its non-productive-time report. 8 files, 302 pages, 1,431 chunks. The validator passes; 441 of 441 end-of-well chunks carry their well; AK-3's part is identical to `ak3-demo-v1`. Converting the two new reports on this laptop's CPU took about 38 minutes.
- **The facts moved with no model call:** `python -m graphrag.factgraph --map-to <release>` maps each fact's chunk through the package's old-to-new map and checks the value again on the new chunk's text. 202 of 216 facts now cite package IDs; 14 keep old IDs because two chunks have no mapping; none failed the check. The runner does this by default (`--facts mapped`).
- **In the stores:** 1,431 chunks, 302 of 302 pages rebuilt, 161 events, 58 of 58 plans, 216 facts; 36 fact chunks are package IDs and all are in PostgreSQL. Loaded twice with the same counts.
- **What it fixes:** with the stores as the source, an exact-mode question about AK-3's casing returned 12 facts and no passage; it now returns 12 facts and 6 passages.
- **Open:** the 14 facts on old IDs; why 56 of 56-32's old chunks have no mapping.

## 2026-11-25 (later): a design review, a code review, and the first runs with the real model

Tri asked for the whole project to be gone over before people are put in front of it: the design, the code, the application, the diagrams and the documents. Hung and Khai gave clearance for their tracks. The work ran in a cloud session with review agents; that machine has 4 CPU cores, 16 GB of memory and Docker, which turned out to be enough to run Qwen3-8B itself, slowly (B-F71).

**B-D49 (decision; the application is built around one model slot and around not losing a question).** Specification D-69. A design review read the second build against its code before the first deployment. Its verdict: the shape is right for this size (one process, the engine in memory, one compose file, one proxy) and nothing should be added to it: no queue service, no answer cache, no streaming. The gaps were operational: nothing bounded waiting, a failed question was lost, the stores did not come back after a reboot, and nobody would have known the demo was down.

**B-C65 (design choice; waiting, failures and readiness in the backend).** `backend/`, 50 tests without a store.

- **Questions take turns with limits.** A question waits at most 60 seconds for the model's slot and at most 8 wait; beyond either the reply is `503` with code `busy` and `Retry-After`. Before, waiting had no bound: a browser that had given up still held its place.
- **The limits are ordered:** one model call 75 seconds, the wait for a turn 60, the browser 240. Before, the model client waited 900 seconds a call and the browser 180, so a hung model blocked everyone for up to half an hour after the asker had left.
- **A failed question is logged**, with status `error` and the kind of failure, and its ID is in the error reply. Before, a question that failed left no trace, so an expert's question was lost and the error rate could not be counted.
- **An answer is never lost to the log.** If the log cannot be written, the answer is returned and the server log has the failure. Before, a PostgreSQL that dropped after the answer was made turned the answer into a `503`.
- **`GET /v1/ready`** asks the model endpoint and the question log, at most once every 15 seconds. `GET /v1/health` stays the cheap check that the process is up.
- **One error shape:** a sentence, a code, and the question's log ID.
- **One line per question in the server log**, as JSON; `python -m backend.questions stats` reads the log into seconds per question (median and 95th percentile), calls and tokens per question, and the shares of errors, "not found" and fallbacks.
- **A reply that should be JSON and is not is not kept in the request cache** by the service, so "Try again" asks the model again. Measurements keep every reply, as before.
- **The search indexes are built at start**, not by the first question.
- **Not done, on purpose:** several questions at once on a hosted endpoint (the engine counts cost per client, so it stays one at a time); an idempotency key (a retried question is logged twice, and answered from the cache); a fallback to BM25 when the embedding server stops after start (the documented choice is to fail, not to search another way quietly).

**B-C66 (design choice; a hosted model only sees packages named as public).** Finding of the review: the client's guard against private data on a hosted endpoint never fired in the backend, because nothing told it what a package holds, and the runbook said it did. The service now checks once, at start: with a hosted endpoint in the roles file and the stores as the source, the loaded package must be named in `BACKEND_PUBLIC_RELEASES`, or the service does not start. A person names it; that is the statement that its reports are public.

**B-C67 (design choice; the stores and the server).** `platform/docker-compose.yml`, `deploy/`, `platform/server/`, with Hung's clearance.

- PostgreSQL and Neo4j restart by themselves and have health checks; the backend starts when they answer. Before, a reboot left the stores down and the backend in a restart loop until someone logged in.
- Neo4j's heap is 512 MB and its page cache 256 MB, with memory limits on every service: the graph is hundreds of nodes and is read once. APOC is no longer installed: nothing in the application calls it, and installing it made an internet download part of every first start.
- The proxy refuses request bodies over 64 kB and sends a content security policy and HSTS.
- `deploy/watch.sh` runs the quick smoke test from another machine every five minutes and posts to the group chat when the application goes down or comes back. `smoke_test.py --quick` asks no question.
- `backup.sh` copies the dumps off the server when `BACKUP_REMOTE` is set, and says so in its log; `restore_check.sh` proves a dump restores. The question log is the one thing that cannot be rebuilt.

**B-F68 (finding; nine of the 216 checked facts were wrong, and the check let them through).** The rule "the value is written in its chunk" was a plain text search, so digits inside a longer number counted.

- Examples that had passed: TG-2 ground elevation 150, from "approximately 1500' elevation"; TG-4 non-productive time 8, from "drilled to 833'"; AK-3 highest measured temperature 180, from a map coordinate "78180.6".
- The check now wants the number written as a number of its own, with trailing zeros allowed ("5.5" is "5.500"). **216 facts become 207:** AK-3 66 to 65, TG-2 10 to 4, TG-4 3 to 1; 56-32 and 68-32 keep theirs.
- B-F62's fact (AK-3, 3 days from spud to release) still passes: a real 3 is written in its chunk for another reason. That kind needs a check on meaning, not on digits.
- The fact sheets of E20, E22 and E27 were made with the old check. Their scores stand as recorded; new runs use the new check, with baselines rerun beside them.

**B-F69 (finding; the scorer had three loopholes, none of which touched a recorded score).** A question with no gold fact counted as correct whenever no value came back, so a broken reply was "correct"; the probe's "fallback" outcome was correct whatever the answer said; and an empty list of causes from a broken reply was a correct "no cause stated". Checked on every recorded run: 0 rows were scored through any of them (2,657 rows, 3 of them invalid replies, all on questions with gold). The rules are now: with no gold, only "not stated" is right; the probe's fallback question must also end as "not stated"; a broken reply is never right. The probe's questions are unchanged; this is the scorer, fixed before its first run.

**B-F70 (finding; other defects from the code review, each fixed with a test in `tests/test_graphrag_review_fixes.py`).**

- **Plan dates were compared as text.** A plan with "20 August 2016" matched no bound and the total came out over the whole well (115 hours for a two-day question that should give 31), reported as calculated. Dates are now put in one form first; a date code cannot read, a reversed range, a negative number or an unknown operation gives "not stated".
- **A date range in a question was read as its last day**, and "August 20, 2016", "2016-08-20" and "20 Aug 2016" as no date at all. All are read now, and a range gives each of its days.
- **A search over no passages divided by zero** (a question naming a well and a day the well has no report for): a 500 in the application.
- **An answer reply with a number where text was asked crashed the run** and, being cached, would have stopped every resume at the same question. Replies are now checked in shape; a wrong shape is an invalid reply.
- **A cause was kept on a one-letter quote.** A quote now needs four letters or digits.
- **Page images were written under the package's file ID and looked up under the report's name**, so no page image could show on a package. Both are tried now.
- **A total could be computed on AK-3 for a question about a well the engine does not hold**, when the model left the well out of the plan. Such a question now has no plan.
- **Rows from cached calls recorded 0 seconds.** They keep what the call took when it was made.
- **The bench's comparison paired the coordinator with the first run of the same set it found**, which could be the quick check or a step on the package. It now takes the hand-routed step, of the same run first.
- **`backend.questions counts` counted a question once per mark.**
- **Left open:** value matching is looser than its description (a numeric gold accepts numbers within 0.5%, so 1955 accepts 1946; the first number in an answer wins; units are not compared). These are the prototype's rules, and changing them means rescoring every baseline: to decide with the first expert-reviewed set. A resumed bench run does not notice a server restarted with another context size or thinking setting: restart with the same command, as the README says.

**B-C68 (design choice; every diagram redrawn in one style and checked against the code).** 15 diagrams. Each box and arrow was checked against the code; the ones that had drifted were redrawn (three lanes for four, MinIO as the file store, a viewer that was never built, the fallback arrow pointing at the wrong lane). One palette with five meanings: people and screens green, our code blue, stores amber, models violet, rented or outside grey and dashed. New: the deployment drawn with its ports and volumes, and "the life of a question" in the engine README in place of the first build's crowded chart. How to export them on Linux is in [docs/diagrams/README.md](../../diagrams/README.md).

**B-C69 (design choice; the application made easier to use, and checked for accessibility).** `frontend/`, 178 tests (140 before). The look is unchanged; what changed is how it behaves with real answers.

- **The answer stays in view.** On a total or a cause, the evidence was four to five thousand pixels of activities and the answer scrolled away. The answer column now stays beside it; activities are grouped by day with a line per day (activities, hours, non-productive hours); a long list shows its first days and a "Show all 28 activities" button. A click on a timeline bar unfolds the list and goes to its row. The same folding on the well page's tables of values at depths.
- **Waiting is told, not hidden.** A real model takes from seconds to minutes. The waiting screen names three steps in plain words, counts the seconds, changes its reassurance as time passes, and has a Stop button that puts the question back in the box. The steps follow the clock: the server reports no progress.
- **Messages match what went wrong:** busy (try again in half a minute), the answering service not responding, the report database not responding. Before, each said to start the model server, which means nothing to an expert.
- **Failed questions show on "Questions people asked"** as "Could not be answered", with a filter and a count.
- **A notice when the system is not ready**, from `GET /v1/ready`, instead of letting the first question fail.
- **Phone:** a one-line header; answer, then evidence, then earlier questions; each activity on two lines instead of a table that scrolls sideways; nothing wider than the screen down to 320 pixels.
- **Accessibility:** an automated scan (axe, WCAG 2.2 AA, 17 screens at two widths) went from 315 findings to 0: landmarks, target sizes, names, keyboard focus in scrolling areas. Tabs and the timeline work by arrow keys; the guide and the page view keep and return focus; tables have headers; non-productive bars are hatched as well as amber. The same scan runs in the tests. **Not done:** a test with a screen reader.
- **Print:** an answer prints with its sources and its whole evidence, without the controls.

**B-F71 (finding; the baseline model runs on a CPU, slowly, and gives the recorded answers).** The cloud session's machine (4 cores, 16 GB, no GPU) ran our own copy of Qwen3-8B (the same 4-bit file) on llama.cpp's CPU build of the same release, b12015.

- **The baseline is reproduced exactly:** BM25, top 5, AK-3, 31 prototype questions: 28/31, the same three questions wrong (q07, q25, q31), and the same status and values on all 31 as the recorded run on the borrowed GPU (E17). So a score from the CPU build stands beside the recorded ones. Run `bench_qwen3-8b.cpu_quick`.
- **Speed:** 136 seconds a question (the GPU: 1.05), about 13 prompt tokens and 2.4 answer tokens a second while sharing the cores with other work. The 31 questions took 70 minutes of model time. The 221 pooled questions would take about a day, so E33 in full still needs a GPU; the short measurements do not.
- **Memory:** this llama.cpp release keeps earlier prompts in memory, up to 8 GB by default, so the server grew from 7 GB to 12 GB during a run and the machine killed it three times before the cause was found. `--cache-ram 0` stops it. Each time the run resumed from the request cache on disk with no lost answer, which is what the resume was built for. A 32k context does not fit in 16 GB.
- **Everything else the measurements need was built on the same machine:** the demo package from the public PDFs (Track A log A-F22), the stores with real vectors (Track C log C-F09), the page images (302 pages in 73 seconds), and the application as containers (C-F10).
- Profile `qwen3-8b.cpu`; the steps are in the [engine README](../../../graphrag/README.md#without-a-gpu-on-linux).

**B-F72 (finding; the first frames from the real model showed where the reasoning lane trusted it too far).** Before any answer about a cause was scored, the ten questions of the probe were framed by Qwen3-8B and the problem each frame leads to was worked out in code (no answer call). As built, the lane found the right outcome on 6 of 10.

| Question | What the model wrote | What the lane did with it, as built | Change |
|---|---|---|---|
| r01, the stuck pipe on 20 August | Non-productive code `STUCK`: the activity code. The reports' non-productive code for that hour is `KICK` | An exact match on the code found no problem; the question fell back to passages and came out "not stated" | A code the reports do not use as a non-productive code is read as one more word naming the problem |
| r09, "what caused the non-productive time" | Code `KICK` and keyword "kick", though the question names neither | One problem picked, where the question fits six and should be asked back | Date, depth and keywords are kept only where the question says them. The code is kept: turning "wait on equipment" into `WOE` is the model's job. So r09 still picks one problem; that is the model's error and is left as one |
| r10, a twist-off that never happened | Keywords "twist-off", "drill", "string" | The KICK incident was picked because one of its events says "drill" | Every keyword must be named somewhere in the problem's activities |
| r06, "what was AK-3 waiting for on 5 September" | Kind `lookup_by_date`, not `cause` | Sent to passages of that day | None: a defensible reading of the question |

- After the three changes the frames lead to the right outcome on 8 of 10 (r06 and r09 remain). The stand-in models used in every earlier test never made these mistakes, which is why tests did not find them.
- **The probe was used to find these faults, so its score after the changes is not a clean test of them.** A second probe, `graphrag/gold/ak3_reasoning_probe_v1.json`, was written after the changes and before any run on it: the same well asked in other words, two questions on causes written in activities that are not non-productive time, one to ask back and one about a failure that did not happen.
- The rule the changes follow is the one the coordinator already had for wells and dates: what code can read from the question or the reports wins over what the model says.

**B-F73 (finding; faults that only the live stack showed).** With the stores as the source and the application opened in a browser:

- A fact's value on a well page did not open its page: on a package the fact named its report by the package's file ID, and the file routes use the report's name. The example data is on the old chunk IDs, where the two are the same, so no test saw it. Fixed, with a test on a package chunk.
- The setting `GRAPHRAG_K1_CHUNKS` given a package's folder, as CLAUDE.md suggests, said the corpus was missing. It accepts the folder now.
- Confirmed working there: page images found under the package's file ID (B-F70), the search in the database chosen at start on real vectors, the readiness check, the proxy's size limit and headers.

**E34 ([record](../../experiments/E34-reasoning-probe.md)): the reasoning lane on its probe, with the real model.** First probe, after the problem finding was corrected: 2/10 correct, the problem found on 8/10, the stated cause found and cited on 8/10, and 17 unsupported claims. Second probe, written before any run on it: 3/10, 6/10, 5/10 and 8. A cause question costs two calls, about 4,800 prompt and 660 completion tokens.

**B-F74 (finding; the lane finds the stated cause and over-states).** From E34.

- **What works:** when the lane reached the right problem, the model named the cause the reports state and quoted the report's words: 8 of 8 on the first probe.
- **What does not:** it also lists things that happened nearby as stated causes, each with a true quote (17 items on 7 answers). The citation check passes them: a real quote is not a reason.
- **Rule added in code:** a stated cause must rest on a clause that gives a reason ("due to", "because", "waiting on", "unable"), once per clause, and not on something written after the day asked about; the rest are shown as possible factors. Unsupported claims: 17 to 8 on the first probe, 8 to 5 on the unseen second one, where it also cost one true cause that the report gives as a purpose ("to stop flow").
- **What remains:** a true reason for a neighbouring event of the same incident. AK-3's 66-hour well-control incident holds a stuck pipe and a lost rod; asked about one, the model gives both reasons. The unit of "the problem" should be an activity or a short run of them, not a whole incident. Next change to try.
- **Two more faults in finding the problem, from the second probe:** a wrong code from the model blocked a date that was right (now the day outranks the code), and an activity that is not non-productive time was not found because every keyword had to match (now one is enough on a named day). Not yet rerun.
- **"Possible factors" are mostly generic** ("inadequate communication"). Whether to keep that part is a question for an expert.

**B-D50 (decision; the reasoning lane continues as a probe, D-66).** It is not shown as a finding to anyone yet. Before more code it needs an expert's reading of ten answers and a question set written by someone else. Ours to do next: a smaller unit for the problem.

**B-F75 (finding; a security review before the first deployment found nothing serious, and two things to fix).** The review read the backend, the proxy, the compose file, the server scripts and the frontend's data handling, and probed the running stack. No injection, path traversal, cross-site scripting, cross-site request forgery or committed secret. Checked and fine, among others: every route asks for the password; every SQL and Cypher value is a bound parameter; the content security policy blocks inline script and the application needs none; another site can neither read nor write through a signed-in browser; no question text in the server log line.

- **Fixed: the hosted-model check believed the endpoints file.** An endpoint marked `"hosted": false` on a public address would have received report text. The backend now counts any address outside this machine and its private network as hosted, whatever the file says (B-C66).
- **Fixed: a NUL character** in a path, a filter or a question ended as a 500 from PostgreSQL, and such a question would have been answered and not logged. It is refused with 422. The list offset has an upper bound.
- **Fixed: containers run with less.** The backend's filesystem is read-only apart from its data volume and `/tmp`, and it holds no capability; the proxy holds only the one to bind its ports. Both ran healthy that way.
- **Fixed: the shared password is no longer on a command line** in the runbook; the smoke test warns when it is pointed at plain HTTP on another machine.
- **Known and accepted:** a wrong password costs the proxy about a tenth of a second or more of CPU (bcrypt), so someone without the password can slow the server by guessing in parallel; with a long random password guessing cannot succeed, and the monitor would show the slowdown. A package named as public is a promise by name. The request cache on the backend's volume grows by a few kilobytes per new question and is never pruned.
- **Not checked:** HTTPS with a real domain; known vulnerabilities in the pinned packages (`npm audit`, `pip-audit` were not run).

**B-F76 (finding; the first real question through the whole application).** The full smoke test passed from outside the proxy with Qwen3-8B answering and the stores as the source: the gate, the frontend, health, readiness, one question, one mark; 6 of 6. "What total depth did well AK-3 reach?" was answered from well facts and passages in 212 seconds on the CPU, with 2 calls and 3,544 prompt tokens, cited to the package's chunk, and written to the question log in PostgreSQL. It showed two faults, both fixed:

- **The answer read "1955 in".** The passage says "1,955 feet in 27 days" and the model gave "in" as the unit. The value was right and was checked; the unit never was. The unit shown is now the one the cited passage writes straight after the value, when it writes one. Scores do not change: the scorer does not compare units.
- **The one line per question never reached the container's log**: the server configures only its own loggers. The service's lines now go to the console.

**B-F77 (finding; a smaller unit for "the problem" removes most of what was left).** The follow-up B-F74 named. An incident can run for days and hold several things that went wrong, and a question is usually about one of them.

- **The rule:** the problem is the activities of the incident on the day asked about, and among them those the question's keywords name. A stated cause stands when its reason is written in those activities. If none is, the reason in the nearest earlier activity stands, since a cause comes before its effect. A reason from a passage stands only when no activity gives one. With no day and no keyword, the whole incident is meant, as before.
- **Nothing the model sees changes**, so the recorded replies were scored again at no cost. First probe: 4 of 10 correct to 6, unsupported claims 8 to 5. The three still wrong: the general question about the whole incident (both reasons are fair there, and the gold names neither), the question the model answered instead of asking back, and one where the same reason is cited from an activity and from a passage.
- **Tuned on the first probe.** Its test is the second probe, to be scored when the model is free.
