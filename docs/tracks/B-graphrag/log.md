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
| Baseline | Plain RAG: Qwen3-8B (thinking off), BM25 routed by the well the question names, top 5, citations and values checked in code: 28/31 on AK-3 and on three reports ([E18](../../experiments/E18-well-routing.md)) | B-D03, B-C08, B-D14, B-D16 |
| Bases to run | neo4j-graphrag-python run and not adopted: its facts do not improve answers ([E16](../../experiments/E16-neo4j-graphrag-python.md)); LightRAG next | B-D04, B-D14 |
| What to adopt | Solutions close to our description, which we then improve | B-D08 |
| Extraction defaults | One pass, constrained JSON, ontology slice only, cache by chunk hash; citations checked in code | B-C01 to B-C04, B-C07 |
| LLM | Qwen3-8B (thinking off) answers best; Qwen3-4B second; Qwen2.5-7B and Llama-3.1-8B abstain and are dropped | B-D06, B-D14 |
| Retrieval | BM25 routed by well (hit@5 1.00 on three reports); fusion with Qwen3-Embedding-0.6B only for questions that name no well | B-F14, B-D12, B-D16 |
| Compute | Desktop RTX 4080 SUPER with llama.cpp (-c 32768 -np 4), one request at a time for measurements; Neo4j in Docker | B-F16, B-C09, B-C10 |
| Next | Graph-worthy questions from the supervisor; filter by well; LightRAG with Qwen3-8B | B-D15 |
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
