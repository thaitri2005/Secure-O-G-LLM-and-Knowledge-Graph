# E19: LightRAG against the plain RAG baseline, and a cross-report probe

| | |
|---|---|
| **Date** | 31 October 2026 |
| **Question** | Does LightRAG, the second candidate base (B-D04, B-D15 step 3), answer better or cheaper than the D-50 baseline? On which questions could a graph help at all? |
| **Requirement** | D-36 (an existing open-source GraphRAG base), D-37 (models of about 7B), D-50 (the baseline); Track B B-D15 |
| **Input** | K1 version 0 chunks: AK-3 pool (60 chunks, 28 pages) and three-report pool (372 chunks) |
| **Code** | `graphrag/lightrag_run.py` (LightRAG 1.5.7, MIT, used as a library in `.venv-lightrag`, `requirements-lightrag.lock.txt`); `graphrag/baseline.py` (`--questions`, `--answer-format`, `--fresh`, `perwell:`) |
| **Gold data** | The prototype's 31 questions and 41 facts; the 9-question cross-report probe ([`cross_report_probe.json`](../../graphrag/gold/cross_report_probe.json), B-C14) |
| **Models** | Qwen3-8B Q4_K_M (thinking off) for extraction, keywords and answers; Qwen3-Embedding-0.6B Q8_0; llama.cpp b12015 on the desktop RTX 4080 SUPER, **`-c 32768 -np 1`** (LightRAG's prompts do not fit an 8k slot), requests one at a time |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E19_*.json` |
| **Status** | Done |

## How LightRAG was run

- **Indexing:** our K1 chunks through `ainsert_custom_chunks` (no re-chunking), LightRAG's default extraction prompt and entity types, one gleaning round (its default), description summaries on merge (its default).
- **Querying:** `aquery_data` returns LightRAG's entities, relations and chunks without an answer. They go into the baseline's answer prompt as "knowledge graph" lines plus passages, and through the same citation check and scoring. Only retrieval differs from the baseline. Chunks map back to K1 IDs by text; 0 were unmapped.
- **Budgets:** `default` is LightRAG's own (40 entities and relations, 20 chunks, up to 30,000 tokens); `small` is close to the baseline (10 entities and relations, 5 chunks, 4,000 tokens).

## Control: the baseline under the new server setting

| Pool | Retriever | Correct | Prompt tokens per question (median) |
|---|---|---:|---:|
| AK-3 | BM25, top 5 | 28/31 | 1,408 |
| Three reports | BM25 routed by well, top 5 | 28/31 | 1,465 |

Both re-measured with `--fresh` (no cache) under `-np 1`: the same 28/31 and the same three misses as E17 and E18 under `-np 4`.

## Indexing cost (AK-3)

| | LightRAG (Qwen3-8B) | neo4j-graphrag ([E16](E16-neo4j-graphrag-python.md), Qwen3-4B) |
|---|---:|---:|
| LLM calls | 122 (4.4 per page) | about 2 per page |
| Tokens | 381,000 (13,600 per page) | about 4,500 per page |
| Seconds | 625 (22 per page) | about 3 per page |
| Graph | 516 entities, 628 relations | — |

- Entity types are LightRAG's generic defaults (artifact 84, event 83, concept 76, location 65, …); 40 entities came back typed `UNKNOWN`. A few extraction outputs lost their delimiters (format warnings in the log), as B-F02 predicts for small models.

## Answers on AK-3 (31 questions)

| Retrieval | Correct | Gold chunk retrieved | No wrong value | Prompt tokens per question (median) | Keyword calls |
|---|---:|---:|---:|---:|---:|
| **Baseline: BM25, top 5** | **28/31** | 23/23 | 21/23 | 1,408 | 0 |
| LightRAG `mix`, small budget | 25/31 | 21/23 | 18/23 | 2,417 | 31 (about 665 tokens each) |
| LightRAG `mix`, default budget | 25/31 | 20/23 | 17/20 | 7,246 | 31 |
| LightRAG `naive` (vector only), default budget | 25/31 | 20/23 | 17/19 | 3,652 | 0 |
| LightRAG `local`, default budget | 21/31 | 19/23 | 14/19 | 6,986 | 31 |

- LightRAG's own cache served the keyword calls of the second and later runs, so our ledger shows them only once; each question costs one keyword call (about 665 tokens) in `mix` and `local` mode.
- The graph context misleads: q03 ("How deep was TG-2 drilled?") got TG-4's 1,500 ft in `mix` and `local` mode.

## The cross-report probe (9 questions, three reports)

| Retrieval, answer format | Correct | Facts with a retrieved passage | Prompt tokens (median) |
|---|---:|---:|---:|
| Well-routed BM25, top 5, status first | 0/9 | — | 1,228 |
| Well-routed BM25, top 10, status first | 0/9 | 6/14 | 2,556 |
| Fusion, top 10, status first | 0/9 | — | 2,428 |
| Well-routed BM25, top 10, evidence first | 2/9 | 6/14 | 2,592 |
| Fusion, top 10, evidence first | 1/9 | — | 2,518 |
| Per-well fusion, top 10, evidence first, "which X" rule | **3/9** | **10/14** | 3,681 |

- **Status first makes the model abstain (B-F22).** Grammar-constrained decoding writes `status` before anything else. On p08 the answer passage was ranked first and the model still said `not_stated`; alone or with one other passage it answered. Writing a short evidence note first fixes p08 and p03.
- **Per-well search** (one search per named well, the other wells' names removed from that search, results interleaved) lifts fact coverage from 6 to 10 of 14. It costs 3 of the 31 single-well questions (25/31), so it should apply only when a question names several wells.
- **What still fails, and why:**

| Question | Failure | Needs |
|---|---|---|
| p01, p04 | The evidence picks the right wells, but the answer value is their depth, not the name | A prompt or schema that separates "which" from "how much" |
| p02, p09 | Not every well's passage retrieved; 68-32's spud date sits in garbled daily-report tables | Per-well facts; Track A table parsing |
| p05 | Routing kept only AK-3 (the question names AK-3; "Utah FORGE" is not a well), so Mary Mann's FORGE roles were never retrieved | A person linked across reports |
| p06 | Solved with the "which X" rule; the 56-32 cover table is scrambled | Track A |
| p07 | Counting reports needs document metadata, not passages | A document or well registry |

## Three reports

**Index.** 372 chunks, 150 pages: 777 LLM calls (5.2 per page), 2.30 million tokens (15,300 per page), 3,302 s (22 s per page), giving 2,114 entities and 3,099 relations. 120 calls (the AK-3 extractions) came from the request cache, so a cold run is somewhat slower. Entity types are generic again (artifact 463, data 343, concept 297, …; 95 `UNKNOWN`).

**The 31 single-well questions.**

| Retrieval | Correct | Gold chunk retrieved | Prompt tokens (median) |
|---|---:|---:|---:|
| **Baseline: BM25 routed by well, top 5** | **28/31** | 23/23 | 1,465 |
| LightRAG `mix`, small budget | 25/31 | 20/23 | 2,395 + keyword call |
| LightRAG `mix`, default budget | 25/31 | 19/23 | 8,912 + keyword call |
| LightRAG `naive`, small budget | 22/31 | 18/23 | 1,080 |

q03 (TG-2's depth) gets TG-4's 1,500 ft again in `mix` mode.

**The probe (9 questions).**

| Retrieval | Correct | Which | Facts with a retrieved passage | Prompt tokens (median) |
|---|---:|---|---:|---:|
| Plain RAG, per-well fusion, top 10 (above) | 3/9 | p03, p06, p08 | 10/14 | 3,681 |
| LightRAG `mix`, small budget | 3/9 | p04, **p05**, p08 | 8/14 | 2,521 + keyword call |
| LightRAG `local`, default budget | 3/9 | **p02**, p03, p04 | 7/14 | 10,044 + keyword call |
| LightRAG `mix`, default budget | 1/9 | p08 | 10/14 | 13,366 + keyword call |
| LightRAG `global`, default budget | 0/9 | — | 6/14 | 13,962 + keyword call |

All LightRAG probe runs used the evidence-first answer format.

- LightRAG answers questions plain RAG never did: **p05** (Mary Mann, a person linked across the AK-3 and FORGE reports) and **p02** (all three total depths in one answer). Its relation lines also make the model answer p04 with well names rather than depths.
- It loses p06, and is not consistent across modes: each mode solves a different subset. Together, plain RAG and LightRAG answer 6 distinct probe questions; no single setup answers more than 3.
- More context hurts: the default budget (13,000+ tokens) answers fewer probe questions than the small one.

## What was learned

1. **LightRAG does not beat plain RAG on the 31 single-well questions,** at any budget or mode, on one report or three, and it costs more: about 15,000 tokens per page to index, and a keyword call plus 1.6 to 6 times the prompt tokens per question.
2. **On questions across wells it helps on different questions, not more of them.** Its graph links a person across reports (p05) and gathers one value from every well (p02), which passages alone did not. Neither approach passes 3/9.
3. **The answer schema's field order matters more than retrieval on hard questions** (B-F22).
4. **Not adopted as the base on this evidence.** Kept as the reference for what a graph adds: entity links across documents. The next test is whether our own ontology (K2) makes its graph more precise (E21).
