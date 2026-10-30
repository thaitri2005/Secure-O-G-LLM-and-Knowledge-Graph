# Ready-made GraphRAG solutions: survey

**Date:** 30 October 2026 · **By:** Track B · **Method:** a quick web and GitHub search.

Stars, last push and licence were read from the GitHub API on 30 October 2026. Claims marked *self-reported* come from the project's own README or paper and are not yet checked by us.

## What we need from a base

These requirements come from the 28 October meeting:

- an existing pipeline we take over, not one we write from scratch (D-36);
- open-weight models of about 7B or smaller through an OpenAI-compatible endpoint (D-37);
- the ontology injected at extraction (§6.2);
- every item keeps its chunk ID (§5.11);
- graph and vector retrieval;
- low cost per page.

## Shortlist

| Repository | Stars · last push · licence | Role | Why | What to take or check |
|---|---|---|---|---|
| [neo4j/neo4j-graphrag-python](https://github.com/neo4j/neo4j-graphrag-python) (PyPI `neo4j-graphrag` 1.23.0) | 1.3k · 2026-10-30 · Apache-2.0 | **Run (first)** | Fits most closely. The schema (node types, relation types, patterns) is the ontology injection. Undefined types can be pruned. Structured output. A lexical graph links each Document to its Chunks (`FROM_DOCUMENT`, `NEXT_CHUNK`). Vector, hybrid and Text2Cypher retrievers. Neo4j-native | Extraction runs per chunk. Check the calls per chunk, whether our chunk IDs can be kept as Chunk node IDs, and whether an OpenAI-compatible `base_url` works with OpenRouter |
| [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) (PyPI `lightrag-hku` 1.5.7) | 40.4k · 2026-10-29 · MIT | **Run (second)** | Most used. No community reports, so fewer calls. Documents can be inserted and deleted incrementally. PostgreSQL can serve every store, and Neo4j and Qdrant are also supported. LLM cache. `naive` mode is a free vector baseline. Citations to source chunks and files | **Its docs give Qwen3-30B-A3B as the "reasonable minimum" extraction model for local use** (B-F03). That conflicts with D-37, so a ~7B run is the real test. The ontology is only a list of entity types. Its long description prompts cost tokens |
| [neo4j-labs/llm-graph-builder](https://github.com/neo4j-labs/llm-graph-builder) | 5.3k · 2026-10-29 · Apache-2.0 | **Learn from (application)** | A finished application close to our target: upload, schema settings, extraction into Neo4j, seven chat modes, sources in answers, per-user token tracking. FastAPI and LangChain backend, React frontend, Docker Compose, Ollama and OpenAI-compatible models | Reference design and code for M2–M4: schema screen, chat modes, token limits. Its default chunk is 100 tokens, which we should not copy blindly |
| [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | 93.2k · 2026-10-30 · Apache-2.0 | **Learn from (application, tables)** | Full RAG application with layout-aware parsing (DeepDoc) and an optional knowledge graph. Two extraction modes: **Light**, which uses LightRAG prompts and fewer tokens, and **General**, which uses GraphRAG prompts with gleaning. Configurable entity types | Shows how a product exposes extraction cost choices. Its parsing is relevant to Track A. Too large to adopt as our base |
| [circlemind-ai/fast-graphrag](https://github.com/circlemind-ai/fast-graphrag) | 4.0k · 2025-11-01 · MIT | **Learn from (efficiency)** | Configured by a domain description, entity types and example queries. Retrieval by personalized PageRank (the HippoRAG idea). *Self-reported* 6× cheaper than Microsoft GraphRAG on one book | The domain, entity-type and example-query configuration is a cheap way to inject an ontology. Low recent activity |
| [TencentCloudADP/youtu-graphrag](https://github.com/TencentCloudADP/youtu-graphrag) | 1.3k · 2026-02-26 · Tencent licence | **Learn from (method)** | Schema-bounded extraction and retrieval: a seed schema limits what is extracted and guides the splitting of a question into sub-queries. *Self-reported* up to 90% fewer tokens (ICLR 2026) | Read for the ontology-at-query-time idea. **Do not copy code until the licence is read** |
| [HKUDS/MiniRAG](https://github.com/HKUDS/MiniRAG) | 2.0k · 2025-10-16 · MIT | **Learn from (small models)** | Built for small models (Qwen2.5-3B, Phi-3.5-mini). Chunks and entities share one graph; retrieval relies on graph structure instead of heavy model reasoning (ACL 2026) | Ideas for retrieval that does not depend on a strong query model. Inactive for a year |
| [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) | 4.1k · 2026-10-06 · MIT | Learn from | Personalized-PageRank retrieval with few LLM calls; good at multi-hop questions | Only if multi-hop questions turn out to matter |
| [gusye1234/nano-graphrag](https://github.com/gusye1234/nano-graphrag) | 4.0k · 2026-01-27 · MIT | Learn from (reading) | A small, readable version of GraphRAG | The quickest way to understand GraphRAG internals before adapting a base |
| [HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything) | 24.3k · 2026-10-28 · MIT | Watch (Track A overlap) | LightRAG with MinerU parsing and table, image and equation processors | Relevant if LightRAG wins and Track A uses MinerU |
| [microsoft/graphrag](https://github.com/microsoft/graphrag) | 36.5k · 2026-10-29 · MIT | Skip as base; reference | Community reports and gleaning make it the most token-heavy option. Incremental updates arrived in 3.x | The reference that others measure against |
| [OpenSPG/KAG](https://github.com/OpenSPG/KAG) | 9.1k · 2026-01-28 · Apache-2.0 | Skip | Logical-form reasoning on a separate graph engine; too heavy for one document and a ~7B model | — |
| [getzep/graphiti](https://github.com/getzep/graphiti) | 32.4k · 2026-10-28 · Apache-2.0 | Skip | Time-aware memory graphs for agents; not document GraphRAG | — |
| [Cinnamon/kotaemon](https://github.com/Cinnamon/kotaemon) | 25.8k · 2026-07-14 · Apache-2.0 | Watch (frontend) | A document-chat UI with GraphRAG options | Possible UI reference for M4 |

## Licences

- MIT and Apache-2.0 projects may be copied or adapted. Keep the copyright notice and record the source in a `NOTICE` file next to the copied code.
- Youtu-GraphRAG uses Tencent's own licence text. Read it before copying anything.
- No code is copied yet.

## Sources

- [GraphRAG-Bench, "When to use graphs in RAG" (ICLR 2026)](https://arxiv.org/abs/2506.05690v3)
- [GraphRAG on consumer hardware with local 7B models](https://arxiv.org/pdf/2605.20815)
- [Neo4j GraphRAG schema features](https://neo4j.com/blog/developer/unleashing-the-power-of-schema/) · [KG builder user guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html)
- [LightRAG README](https://github.com/HKUDS/LightRAG)
- [llm-graph-builder README](https://github.com/neo4j-labs/llm-graph-builder)
- [RAGFlow knowledge graph docs](https://ragflow.io/docs/construct_knowledge_graph) · [RAGFlow GraphRAG internals (DeepWiki)](https://deepwiki.com/infiniflow/ragflow/6.4-graphrag-and-knowledge-graph-construction)
- [fast-graphrag README](https://github.com/circlemind-ai/fast-graphrag)
- [Youtu-GraphRAG paper](https://arxiv.org/abs/2508.19855)
- [MiniRAG paper](https://arxiv.org/pdf/2501.06713v2)
- [Awesome-GraphRAG list](https://github.com/DEEP-PolyU/Awesome-GraphRAG)
- Small models and structured output (secondary sources, unverified): [premai lightweight models](https://www.premai.io/blog/best-lightweight-language-models-worth-running/), [structured extraction](https://bestllmfor.com/best/structured-data-extraction-json/)
- Embeddings (secondary sources, unverified): [theairankings](https://theairankings.com/best-embedding-models/), [premai](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/)
