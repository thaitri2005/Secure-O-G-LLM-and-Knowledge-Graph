# E14: Plain RAG baseline on the AK-3 end-of-well report

| | |
|---|---|
| **Date** | 30 October 2026 |
| **Question** | How well, and at what cost, does plain retrieval with a small open model answer the prototype's questions? This is the bar every GraphRAG candidate must beat (Track B, B-D03) |
| **Requirement** | D-36, D-37, D-44; Track B decisions B-D01 to B-D03 |
| **Input** | K1 version 0 chunks from `data/processed/gdr_chunks_full.jsonl`. Pools: 15 prototype chunks; the whole AK-3 end-of-well report (60 chunks); AK-3 plus two other end-of-well reports (372 chunks) |
| **Code** | [`graphrag/`](../../graphrag/README.md): `client.py`, `retrieval.py`, `scoring.py`, `baseline.py`; tests in `tests/test_graphrag.py` |
| **Gold data** | The prototype's 31 questions and 41 gold facts, unchanged (development, in-sample; AI-assisted single annotator) |
| **Models** | Qwen3-4B-Instruct-2507 Q4_K_M and Qwen3-Embedding-0.6B Q8_0, both served by llama.cpp (build 10816) on the laptop CPU (i5-1340P, 16 GB; `--device none`). Hosted endpoints were not used |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E14_retrieval_*.json` and `E14_answers_bm25_k5_qwen3-4b.json` |
| **Status** | Done for retrieval and for one answer configuration. Dense retrieval on the 372-chunk pool was not run (B-D09) |

## Retrieval

Each question with a gold fact (23 of them) counts as a hit at *k* when any chunk that states the gold fact is among the top *k*.

| Pool | Retriever | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | Index time | Query time (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 15 chunks | BM25 | 0.87 | 1.00 | 1.00 | 1.00 | 0.92 | 0.01 s | <1 ms |
| 15 chunks | Qwen3-Embedding-0.6B | 0.57 | 0.83 | 0.83 | 0.96 | 0.71 | 170 s | 7.4 s |
| 15 chunks | Fusion (BM25 + dense) | 0.74 | 0.91 | 1.00 | 1.00 | 0.82 | 170 s | 6.5 s |
| 60 chunks (AK-3) | BM25 | 0.70 | 0.96 | 1.00 | 1.00 | 0.81 | 0.1 s | 6 ms |
| 60 chunks (AK-3) | Qwen3-Embedding-0.6B | 0.52 | 0.78 | 0.78 | 0.83 | 0.65 | 614 s | 5.8 s |
| 60 chunks (AK-3) | Fusion (BM25 + dense) | 0.61 | 0.83 | 0.87 | 0.96 | 0.73 | 614 s | 5.9 s |
| 372 chunks (3 reports) | BM25 | 0.39 | 0.78 | 0.78 | 0.91 | 0.59 | 0.2 s | 10 ms |

- Dense timings reflect a laptop shared with other work, at 18 to 80 embedded tokens per second (11,275 tokens for the AK-3 report). Read them as "expensive here", not as the cost of the model.
- On this pool and these questions, BM25 is both better and much cheaper. The questions name wells, depths and casing sizes, so they are keyword-heavy.
- With two other reports added, BM25's hit@5 falls from 1.00 to 0.78. Restricting retrieval to the right document or well will be needed as the corpus grows.

## Answers

The configuration was BM25 over the AK-3 report, the top 5 chunks, Qwen3-4B-Instruct-2507, and JSON-schema output. The prompt asked for the value, unit, chunk ID and an exact quote, and for `not_stated` when the passages do not give the answer. Scoring follows the prototype's rules (`graphrag/scoring.py`).

| Measure | Result | E10 (prototype, for reference) |
|---|---:|---:|
| Correct, all 31 questions | **21/31** | 23/31 |
| Answerable | 9/18 | — |
| Paraphrase | 3/4 | — |
| Not stated in the report | 3/3 | — |
| Unsupported | 4/4 | — |
| Injection | 2/2 | — |
| Answers with no wrong value | 13/15 | 0 wrong values |
| A gold chunk was among the 5 passages | 23/23 | — |
| Cited chunk was among the passages | 10/15 | — |
| Quote found verbatim in the cited chunk | 5/15 | — |
| Invalid JSON outputs | 0/31 | — |

E10 is a different system: it extracts into a graph, reviews the extracted facts and answers from templates. The comparison is indicative only.

**Cost.**

| Measure | Value |
|---|---|
| LLM calls | 31 |
| Prompt tokens | 44,876 (median 1,404 per question) |
| Completion tokens | 2,232 (median 23 per question) |
| Time | 3,714 s in total; median 104 s per question on the shared laptop CPU |
| Cost | US$0, because everything ran locally |
| Indexing | BM25 only; no LLM calls and no embeddings |

**The 10 misses.**

| Cause | Questions |
|---|---|
| Table chunk was retrieved, but the model said "not stated" | q12 (casing table), q16 (survey table), q18 and q21 (rig-time table). q15 has both a table and a text chunk for its gold fact |
| Text chunk was retrieved, but the model said "not stated" | q03, q04 (TG-2 and TG-4 depths mentioned in passing), q06 (planned days) |
| Wrong value format | q07 gave "18 August 2016" instead of the requested `YYYY-MM-DD` |
| Extra value | q05 gave both 19 (spud to release) and 27 (whole project) |

## What was learned

1. **Retrieval is not the bottleneck on one report: reading is.** All 23 gold facts were in the passages the model saw. The 4B model abstained too readily, especially on tables shown as flattened text. That is the gap a graph built from extracted facts, and better table handling (Track A), should close.
2. **Abstention and safety are already strong.** The model never answered the 9 questions that should get no answer: 3 not stated, 4 unsupported and 2 injections. Constrained JSON never failed.
3. **Citations are weak.** Quotes match the chunk verbatim only 5 times in 15, and 5 citations point outside the passages, because the model invents or reformats IDs and quotes. Citations should be attached in code from the retrieved IDs, or checked after the call, rather than trusted to the model.
4. **Prompt cost dominates.** About 1,400 prompt tokens per question against 23 output tokens. Passing fewer or shorter passages, and caching, are the efficiency levers. On OpenRouter at typical small-model prices this is a fraction of a cent per question; on this laptop it is about 100 s.

## Next

- Rerun with normalized dates checked in code and a citation check done after the call. Try *k* = 3 to cut prompt tokens.
- Run the same 31 questions through neo4j-graphrag-python on the same chunks and model (B-D04).
- Repeat on OpenRouter when the key is available, to get comparable speed and cost.
