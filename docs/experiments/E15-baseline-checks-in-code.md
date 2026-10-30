# E15: Plain RAG baseline with citations and values checked in code

| | |
|---|---|
| **Date** | 31 October 2026 |
| **Question** | Does checking citations and normalizing values in code (B-C07) strengthen the E14 baseline, and does *k* = 3 cut cost without losing answers? Is dense retrieval worth retrying on fast compute? (Track B, B-D10 step 1) |
| **Requirement** | D-36, D-37, D-44; Track B decisions B-D02, B-D09, B-D10 |
| **Input** | Same as [E14](E14-plain-rag-baseline.md): K1 version 0 chunks, AK-3 pool (60 chunks, 28 pages) and the three-report pool (372 chunks) |
| **Code** | [`graphrag/`](../../graphrag/README.md): new `citations.py`; `scoring.normalize`; `baseline.py` reports checked citations. Tests in `tests/test_graphrag.py` |
| **Gold data** | The prototype's 31 questions and 41 gold facts, unchanged |
| **Models** | Qwen3-4B-Instruct-2507 Q4_K_M and Qwen3-Embedding-0.6B Q8_0, served by llama.cpp b12015 (CUDA 12.4) fully on the GPU of a desktop: RTX 4080 SUPER 16 GB, Ryzen 9 9900X, 32 GB. Hosted endpoints were not used |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E15_answers_bm25_k5_qwen3-4b.json`, `E15_answers_bm25_k3_qwen3-4b.json`, `E15_retrieval_ak3.json`, `E15_retrieval_three.json` |
| **Status** | Done |

## What changed from E14

- **Values are normalized in code** after the call: dates become `YYYY-MM-DD`, thousands separators go, and duplicate values in one answer are merged. The model's raw values are kept in the result file.
- **Citations are checked in code.** The model's citation stands only if the cited chunk was retrieved and the quote appears in it. Otherwise the citation is attached from the retrieved chunk containing the quote, then from the one containing the value. An answer that no retrieved chunk supports gets no citation.
- The prompt, retriever and model are unchanged, so the prompt tokens match E14 exactly (44,876).

## Setup check

E14's configuration reran on the new machine with E14's code and gave 21/31, the same total, with the same prompt tokens. One answerable question flipped in each direction (q25 is now wrongly answered). GPU decoding is not bit-for-bit repeatable, so completion tokens differ by about 0.5% between runs; read differences of one question as noise.

## Answers

| Measure | E14 | E15, *k* = 5 | E15, *k* = 3 |
|---|---:|---:|---:|
| Correct, all 31 | 21/31 | **22/31** | 20/31 |
| Answerable | 9/18 | 11/18 | 9/18 |
| Paraphrase | 3/4 | 3/4 | 2/4 |
| Not stated | 3/3 | 2/3 | 3/3 |
| Unsupported + injection | 6/6 | 6/6 | 6/6 |
| Gold chunk among the passages | 23/23 | 23/23 | 22/23 |
| Model's quote verbatim in its cited chunk | 5/15 | 7/17 | 2/13 |
| **Citation supported after the code check** | — | **16/17** | **13/13** |
| Checked citation is on a gold chunk | — | 15/16 | 13/13 |
| Invalid JSON | 0/31 | 0/31 | 0/31 |

Where the checked citations came from (*k* = 5): 15 kept from the model, 6 found by quote, 3 found by value, 1 unsupported (q25, the made-up inclination).

**Cost.**

| Measure | E14 (laptop CPU) | E15, *k* = 5 | E15, *k* = 3 |
|---|---:|---:|---:|
| LLM calls | 31 | 31 | 31 |
| Prompt tokens | 44,876 | 44,876 | 28,317 (−37%) |
| Completion tokens | 2,232 | 2,752 | 1,799 |
| Prompt tokens per question, median | 1,404 | 1,404 | 944 |
| Time, total | 3,714 s | **25.4 s** | 17.1 s |
| Time per question, median | 104 s | 0.68 s | 0.33 s |
| Cost | US$0 | US$0 | US$0 |

**The 9 misses at *k* = 5.**

| Cause | Questions |
|---|---|
| Table chunk retrieved, model said "not stated" | q12, q16, q18, q21 |
| Text chunk retrieved, model said "not stated" | q03, q04, q06 |
| Extra value (19 and 27 days) | q05 |
| Answered a question the report does not answer (inclination at 1,000 ft; the code check found no support) | q25 |

Date normalization fixed q07. Nothing else moved.

## Retrieval on fast compute

| Pool | Retriever | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | Index time |
|---|---|---:|---:|---:|---:|---:|---:|
| 60 chunks (AK-3) | BM25 | 0.70 | 0.96 | **1.00** | 1.00 | 0.81 | <0.1 s |
| 60 chunks (AK-3) | Qwen3-Embedding-0.6B | 0.52 | 0.78 | 0.78 | 0.87 | 0.65 | 1.1 s |
| 60 chunks (AK-3) | Fusion | 0.65 | 0.83 | 0.87 | 0.96 | 0.75 | 1.1 s |
| 372 chunks (3 reports) | BM25 | 0.39 | 0.78 | 0.78 | 0.91 | 0.59 | <0.1 s |
| 372 chunks (3 reports) | Qwen3-Embedding-0.6B | 0.52 | 0.78 | 0.78 | 0.83 | 0.64 | 4.8 s |
| 372 chunks (3 reports) | Fusion | 0.61 | 0.74 | **0.91** | 0.96 | 0.71 | 4.8 s |

- Dense quality matches E14; only the speed changed (AK-3 index 614 s → 1.1 s; query 5.8 s → 0.13 s).
- On one report, BM25 alone is best. With distractor reports, fusion lifts hit@5 from 0.78 to 0.91: the two retrievers miss different questions.

## What was learned

1. **The code checks pay for themselves.** Every answer with any support in the passages now carries a citation that is verifiably in a retrieved chunk (16/17), against 7/17 for the model's own quotes. The one unsupported answer is exactly the wrong one (q25), so "no supported citation" is a usable signal to withhold an answer.
2. ***k* = 3 is not worth it.** It saves 37% of prompt tokens but loses two answers and one retrieval hit. Keep *k* = 5.
3. **The remaining gap is reading, as in E14.** Seven of nine misses are the 4B model abstaining on passages that hold the answer, four of them tables. A larger model (Qwen3-8B), better table text from Track A, and extracted facts (neo4j-graphrag-python) are the levers.
4. **A desktop GPU makes runs cheap enough to repeat.** One full 31-question run takes about 25 s, so model and prompt comparisons can run several times to average out noise.

## Next

- Withhold answers with no supported citation, and measure the effect (should fix q25 without losing others).
- Run the same baseline with Qwen3-8B and Qwen2.5-7B-Instruct locally, to see how much of the reading gap is model size.
- Run neo4j-graphrag-python as E16 (B-D10 step 2).
- Use fusion retrieval once the corpus holds more than one report.
