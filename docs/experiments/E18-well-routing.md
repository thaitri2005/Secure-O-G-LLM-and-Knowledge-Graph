# E18: Routing retrieval by the well a question names

| | |
|---|---|
| **Date** | 31 October 2026 |
| **Question** | Distractor reports bring wrong values (E17: 28/31 on AK-3 alone, 26/31 on three reports). Does restricting retrieval to the documents that name the asked-about well recover the one-report result? (Track B, B-D15 step 2) |
| **Requirement** | §5.11 (well registry IDs in the vector payload); FR-26; Track B B-D15 |
| **Input** | K1 version 0 chunks, three-report pool (372 chunks: AK-3 plus the 56-32 and 68-32 end-of-well reports) and the AK-3 pool (60 chunks) |
| **Code** | `graphrag/retrieval.py`: every retriever takes an `allowed` chunk set, applied before ranking like a vector-store payload filter; `WellRouter` maps well names in the question to the documents naming them; BM25 computes term statistics over the allowed chunks. `graphrag/baseline.py`: retriever spec `wells:<retriever>` |
| **Gold data** | The prototype's 31 questions and 41 gold facts, unchanged |
| **Models** | Qwen3-8B Q4_K_M (thinking off) on llama.cpp b12015, desktop RTX 4080 SUPER, `-c 32768 -np 4 -ngl 99`, requests one at a time; Qwen3-Embedding-0.6B Q8_0 for fusion |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E18_retrieval_three.json`, `E18_retrieval_ak3.json`, `E18_answers_three_wells-*.json` |
| **Status** | Done |

## How routing works

1. Well names are found with one pattern for the forms these reports use (`AK-3`, `TG-2`, `56-32`); casing sizes such as `4-1/2` are skipped.
2. Each document's set of well names stands in for the "well registry IDs" of the vector payload (§5.11) until Track C's registry exists.
3. A question that names a well is searched only in the documents that name it. A question naming no well, or only wells no document names, is not filtered.

On the 31 questions, all 27 that name AK-3, TG-2 or TG-4 route to the AK-3 report; q27 to q30 (off-topic, unknown well XZ-99, injection) are not filtered.

## Retrieval (questions with gold, 23)

| Pool | Retriever | Hit@1 | Hit@5 | Hit@10 | MRR | Index s | Query ms |
|---|---|---:|---:|---:|---:|---:|---:|
| Three reports | BM25 | 0.39 | 0.78 | 0.91 | 0.59 | 0.01 | 0.2 |
| Three reports | Fusion (BM25 + Qwen3-Embedding-0.6B) | 0.61 | 0.91 | 0.96 | 0.71 | 4.8 | 134 |
| Three reports | **Well-routed BM25** | **0.70** | **1.00** | **1.00** | **0.81** | 0.01 | 0.3 |
| Three reports | Well-routed fusion | 0.65 | 0.87 | 0.96 | 0.75 | 4.8 | 168 |
| AK-3 only | BM25 | 0.70 | 1.00 | 1.00 | 0.81 | 0.00 | 0.1 |

- A first version kept BM25's term statistics from all three reports after filtering: hit@5 0.91. Computing them over the allowed chunks, as a separate index per well would, gives exactly the AK-3-only result.
- Routed fusion is worse than routed BM25: inside one report, dense retrieval is the weaker ranker (E14), and fusion pulls BM25 down.

## Answers (three-report pool, Qwen3-8B, top 5)

| Retriever | Correct | Answerable | Gold chunk retrieved | No wrong value | Prompt tokens | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| BM25 ([E17](E17-model-sweep.md)) | 22/31 | 10/18 | 18/23 | 14/19 | 44,430 | 26 |
| Fusion (E17) | 26/31 | 13/18 | 21/23 | 18/22 | 40,703 | 31 |
| **Well-routed BM25** | **28/31** | **17/18** | **23/23** | 21/23 | 45,409 | 33 (E17 calls reused) |
| Well-routed fusion | 26/31 | 14/18 | 20/23 | 18/21 | 42,523 | 27 |

- Well-routed BM25 sends the same passages as the AK-3-only run for all 27 routed questions, so all 31 calls were served from the cache of E17's runs. Its score equals the one-report baseline: 28/31.
- The three misses are the same as on one report, and are reading errors: q07 drops the year from "spud on 18 August and … released 5 September 2016"; q25 takes 1° from the wrong rows of the survey table; q31 refuses an injected question that also asks a real one.
- Cost: no LLM call and no embedding are added; routing is a set lookup.

## What was learned

1. **Routing by the well the question names removes the distractor-report losses completely** on these questions, at no cost. Plain BM25 is again enough; dense retrieval is not needed while questions name their well.
2. **Term statistics must follow the filter.** A shared BM25 index filtered after scoring under-weights terms that are rare in the target report but common in the others.
3. **These questions all name one well.** Routing does nothing for questions that name no well or several wells and ask across reports: those are where a graph or entity registry should earn its place (B-D15 step 1).
