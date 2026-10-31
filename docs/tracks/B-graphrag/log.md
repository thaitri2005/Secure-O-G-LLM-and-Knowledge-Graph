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
| Data this stint | 15 AK-3 EOWR chunks, then the whole AK-3 EOWR | B-D01 |
| Quality yardstick | Prototype's 31 questions and E10 gold facts | B-D01 |
| Efficiency | Calls, tokens, seconds and cost per page and per question on every run | B-D02 |
| Baseline | Plain RAG: Qwen3-8B (thinking off), BM25 routed by the well the question names, top 5, citations and values checked in code: 28/31 on AK-3 and on three reports ([E18](../../experiments/E18-well-routing.md)). Best on the cross-report probe: plus validated per-well facts, 5/9 ([E20](../../experiments/E20-well-fact-sheet.md)) | B-D03, B-C08, B-D14, B-D16, B-D19 |
| Bases to run | neo4j-graphrag-python ([E16](../../experiments/E16-neo4j-graphrag-python.md), [E20](../../experiments/E20-well-fact-sheet.md)) and LightRAG ([E19](../../experiments/E19-lightrag.md)) run and not adopted; LightRAG with K2 injected next (E21) | B-D14, B-D18 |
| What to adopt | Solutions close to our description, which we then improve | B-D08 |
| Extraction defaults | One pass, constrained JSON, ontology slice only, cache by chunk hash; citations checked in code | B-C01 to B-C04, B-C07 |
| LLM | Qwen3-8B (thinking off) answers best; Qwen3-4B second; Qwen2.5-7B and Llama-3.1-8B abstain and are dropped | B-D06, B-D14 |
| Retrieval | BM25 routed by well (hit@5 1.00 on three reports); fusion with Qwen3-Embedding-0.6B only for questions that name no well | B-F14, B-D12, B-D16 |
| Compute | Desktop RTX 4080 SUPER with llama.cpp (-c 32768 -np 4), one request at a time for measurements; Neo4j in Docker | B-F16, B-C09, B-C10 |
| Next | Graph-worthy questions from the supervisor; LightRAG with K2 (E21); validated per-well facts as the graph part, to repeat on the expert set | B-D19 |
| Ontology (K2) | Version 1: 9 entity types, 13 relations, 19 properties, 104 generated glossary entries ([k2_eowr_v1.json](../../../configs/ontology/k2_eowr_v1.json)) | B-D17 |
| Questions | Prototype 31 for development; a 9-question cross-report probe (not an evaluation set) for graph-worthy questions | B-C14 |
| Vector store | Open; decided with Track C after the base | — |

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

