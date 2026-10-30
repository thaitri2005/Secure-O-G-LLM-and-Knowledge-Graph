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
| Baseline | Plain vector RAG | B-D03 |
| Bases to run | neo4j-graphrag-python, then LightRAG | B-D04 |
| What to adopt | Solutions close to our description, which we then improve | B-D08 |
| Extraction defaults | One pass, constrained JSON, ontology slice only, cache by chunk hash | B-C01 to B-C04 |
| LLM | Open: Qwen3-4B-Instruct-2507, Qwen2.5-7B-Instruct, Qwen3-8B, Llama-3.1-8B-Instruct (8B allowed) | B-F10, B-D06 |
| Embeddings | Open: Qwen3-Embedding-0.6B, bge-m3 | B-F11 |
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
