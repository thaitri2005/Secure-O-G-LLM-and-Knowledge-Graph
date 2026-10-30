# E17: Answer models and multi-report retrieval for the plain RAG baseline

| | |
|---|---|
| **Date** | 31 October 2026 |
| **Question** | How much of the baseline's reading gap is the model? Does withholding answers without a supported citation help? How does the best model hold up with two distractor reports? (Track B, B-D13) |
| **Requirement** | D-37 (models of about 7B; 8B allowed, B-D06); Track B decisions B-D12, B-D13 |
| **Input** | K1 version 0 chunks: AK-3 pool (60 chunks) and three-report pool (372 chunks) |
| **Code** | `graphrag/baseline.py` (unchanged prompt, BM25 or fusion, top 5); `--withhold-unsupported` added |
| **Gold data** | The prototype's 31 questions and 41 gold facts, unchanged |
| **Models** | Q4_K_M GGUFs on llama.cpp b12015, desktop GPU, `-c 32768 -np 4`, requests one at a time: Qwen3-4B-Instruct-2507 (`unsloth`), Qwen3-8B (`Qwen/Qwen3-8B-GGUF`, thinking switched off with `--chat-template-kwargs {"enable_thinking":false}`), Qwen2.5-7B-Instruct and Meta-Llama-3.1-8B-Instruct (`bartowski`). Qwen3-Embedding-0.6B Q8_0 for fusion |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E17_answers_*.json` |
| **Status** | Done |

## Answer models (AK-3 pool, BM25, top 5)

| Model | Correct | Answerable | Paraphrase | Not stated | Unsupported | Injection | No wrong value | Prompt tokens | Seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 ([E16](E16-neo4j-graphrag-python.md) control) | 23/31 | 12/18 | 3/4 | 2/3 | 4/4 | 2/2 | 16/18 | 44,876 | 27 |
| **Qwen3-8B** | **28/31** | **17/18** | 4/4 | 2/3 | 4/4 | 1/2 | 21/23 | 45,000 | 33 |
| Qwen2.5-7B-Instruct | 8/31 | 0/18 | 0/4 | 3/3 | 4/4 | 1/2 | — | 44,876 | 14 |
| Llama-3.1-8B-Instruct | 10/31 | 2/18 | 0/4 | 3/3 | 4/4 | 1/2 | 2/3 | 42,457 | 21 |
| *E10 prototype (for reference)* | *23/31* | | | | | | *0 wrong* | | |

- **Qwen3-8B reads the tables the 4B model abstained on** (casing, survey and rig-time tables). Its three misses: q07 gave "18 August" without the year; q25 answered 1° for a depth the survey skips; q31 (an injection wrapped around a real question) was refused.
- **Qwen2.5-7B and Llama-3.1-8B abstain on almost everything** under this prompt. A probe showed Qwen2.5-7B does answer without the JSON schema (wrongly: 255 ft for the total depth), and still abstains when the JSON shape is spelled out in the prompt. They are dropped as answer models for this harness; prompt work could change that, but Qwen3-8B wins without it.
- Thinking stayed off for Qwen3-8B, so its cost is close to the 4B model's: a median of 1,408 prompt tokens per question, about 80 output tokens and 1 s per question on average.

## Withholding unsupported answers (Qwen3-4B, E15 calls rescored)

After the citation check learned to ignore thousands separators (`1955` against `1,955`), every one of the 17 answers had a supported citation, so `--withhold-unsupported` withheld nothing: 22/31, the same as E15. A citation check cannot catch a value read from the wrong row of the right table (q25). See the correction in [E15](E15-baseline-checks-in-code.md).

## Two distractor reports (three-report pool, Qwen3-8B, top 5)

| Retriever | Correct | Answerable | Gold chunk retrieved | No wrong value | Prompt tokens | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 22/31 | 10/18 | 18/23 | 14/19 | 44,430 | 26 |
| **Fusion (BM25 + Qwen3-Embedding-0.6B)** | **26/31** | 13/18 | 21/23 | 18/22 | 40,703 | 31 |

- Fusion's retrieval gain (E15) carries through to answers: +4 questions.
- Distractor reports bring wrong values: with BM25, q01 answered 7,625 ft, another well's depth. Restricting retrieval to the asked-about well or document (§5.11 ID payload) is the next lever.
- Two dates lost their year ("18 August", "5 September"); normalization in code cannot restore a year the model dropped.

## What was learned

1. **The model is the main lever for reading.** Qwen3-8B at the same prompt and cost per question answers 28/31 against 23/31 for the 4B model, beating the E10 prototype.
2. **Model families differ sharply under a JSON-schema prompt that allows abstaining.** Qwen2.5-7B and Llama-3.1-8B abstain; candidates must be tested on our harness, not chosen from rankings.
3. **Across several reports, fusion retrieval matters,** and so will filtering by well or document.
