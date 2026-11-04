# E26: Routing by number of wells, and stricter fact checks, on held-out questions

| | |
|---|---|
| **Date** | 4 November 2026 |
| **Question** | E23 suggested using per-well retrieval only for questions naming several wells, and tightening the validator. Do both hold on questions written after that idea? |
| **Requirement** | B-F32, B-F33 |
| **Input** | K1 version 0, three-report pool (372 chunks, 150 pages) |
| **Code** | `graphrag/baseline.py` (`--multi-well-retriever`, `--strict-facts`), `graphrag/validate.py` (`strict`) |
| **Gold data** | [`simulated_heldout_v0.json`](../../graphrag/gold/simulated_heldout_v0.json): 36 questions, frozen before any run, weighted to questions naming two wells. **Simulated: no drilling expert has reviewed it.** Same author and reports as E23's set, so held out from the rule but not independent of it |
| **Models** | Qwen3-8B (thinking off), `-c 32768 -np 1 -ngl 99`, one request at a time; Qwen3-Embedding-0.6B. Fact sheet: E20 and E22 facts, not rebuilt |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E26_*.json`; K4 records in `E26_plain_routed.k4.jsonl` |
| **Status** | Done |

## What the settings do

- **Routed:** questions naming two or more wells use per-well fusion, top 10, evidence first. All others use BM25 routed by well, top 5, status first.
- **Strict facts:** a casing size must look like one and be written in the fact's chunk, the value must differ from the size, a depth context must be in the chunk, and planned facts are hidden unless the question asks about a plan.

## Results on the 36 held-out questions

| Setup | Correct | Wrong values | Abstentions | Prompt tokens, median | Completion tokens, median | Seconds, median |
|---|---:|---:|---:|---:|---:|---:|
| Plain, top 5 | 20 | 5 | 11 | 1,474 | 72 | 1.27 |
| Plain, always per well | 23 | 7 | 6 | 3,197 | 222 | 2.98 |
| **Plain, routed** | **23** | 7 | 6 | **2,249** | 140 | 1.72 |
| Fact sheet, routed | 21 | 9 | 6 | 2,464 | 144 | 1.77 |
| Fact sheet, routed, strict | 23 | 7 | 6 | 2,360 | 150 | 1.68 |

Abstentions here are the wrong ones. All setups have 1 LLM call per question and cost $0 (local), and none of these figures counts query embeddings or the dense index. The strict run took 11 of its answers from the cache, so its seconds are slightly low. Plain, routed was rerun uncached with the same answers scored the same.

| Kind | Questions | Plain, top 5 | Always per well | Routed | Sheet, routed | Sheet, routed, strict |
|---|---:|---:|---:|---:|---:|---:|
| Lookup | 18 | 15 | 15 | 15 | 14 | 15 |
| Two wells, list | 8 | 1 | 4 | 4 | 3 | 4 |
| Two wells, compare | 5 | 0 | 0 | 0 | 0 | 0 |
| Must not answer | 5 | 4 | 4 | 4 | 4 | 4 |

Regression checks on question sets already seen:

| Setup | Prototype 31 | Simulated 40 |
|---|---:|---:|
| Plain, routed | 28 (2 wrong) | 31 (1 wrong) |
| Fact sheet, routed, strict | 31 (0 wrong) | 31 (1 wrong) |

Routing does not touch the prototype's questions, which name one well, so 28/31 is the E18 baseline. E23's computed figures were 31/40 for plain, confirmed here by a real run, and 32/40 for the design, which came out 31/40.

The strict check removed 28 more facts: 14 with a context that is no casing size, 11 with a context not in the chunk, 3 whose value repeats the size.

## What was learned

1. **Routing is worth adopting.** It matches always-per-well at 23/36 with 30% fewer prompt tokens per question (35% in total, 97,939 against 150,907), and gains 3 questions on top 5, all on questions naming two wells.
2. **It has a price:** wrong values rise from 5 to 7.
3. **Strict checks are worth adopting whenever a fact sheet is used.** They recover the sheet's 2-question loss and remove the wrong answers it caused on these questions (h22). The prototype's 31/31 is the first perfect score there, but that set shaped the design, and adding facts in E27 moved it back to 30/31, so read it as "about 30", not as perfect.
4. **The fact sheet still does not beat plain RAG on new questions:** 23 against 23.
5. **Comparison questions are unsolved:** 0/5 in every setup. The model abstains, returns the numbers instead of the well (h29: `1955`, `1000`), or picks the wrong well (h30, h31). A small step that compares values in code is the obvious candidate; it was not tried.

## Limits

- 36 questions, one author. Differences of one or two questions are noise, and the gain from routing is 3.
- The set is deliberately weighted to two-well questions, so its total does not compare with E23's.
- Strict checks catch facts whose context is malformed, not all wrong facts: `933.22`, a float collar depth stated with a casing size written in the same chunk, still passes.
- `WELL_NAME` does not match a well name followed by a period ("Well 68-32."), so such a mention is not routed. Not fixed here, because it could change baseline results; no question in these sets is affected, since questions end in `?` or a word.
