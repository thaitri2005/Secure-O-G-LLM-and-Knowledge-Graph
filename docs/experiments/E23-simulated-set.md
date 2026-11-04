# E23: Working design against plain RAG on the simulated question set

| | |
|---|---|
| **Date** | 4 November 2026 |
| **Question** | The 31 development questions are mostly single-fact lookups. On a harder set with comparisons, cross-report and must-not-answer questions, does the validated per-well fact graph (E22) beat plain RAG? |
| **Requirement** | B-D21, B-D22, D-50 |
| **Input** | K1 version 0, three-report pool (372 chunks, 150 pages) |
| **Code** | `graphrag/baseline.py`, no code changes |
| **Gold data** | [`simulated_expert_v0.json`](../../graphrag/gold/simulated_expert_v0.json): 40 questions, frozen before this run. **Simulated: no drilling expert has reviewed it, so this is not expert validation** |
| **Models** | Answers: Qwen3-8B (thinking off), `-c 32768 -np 1 -ngl 99`, one request at a time. Embeddings: Qwen3-Embedding-0.6B. Fact sheet: E20's Qwen3-4B facts and E22's table facts, not rebuilt |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E23_*.json`, and `E23_*_repeat.json` for the uncached repeats |
| **Status** | Done |

## Setups

| Name | Retrieval | Answer format | Fact sheet |
|---|---|---|---|
| Plain | BM25 routed by well, top 5 | Status first | None |
| Design | BM25 routed by well, top 5 | Status first | Validated, top 3 properties |
| Plain, per well | Per-well fusion, top 10 | Evidence first, 700 tokens | None |
| Design, per well | Per-well fusion, top 10 | Evidence first, 700 tokens | Validated, top 3 properties |

## Results

| | Plain | Design | Plain, per well | Design, per well |
|---|---:|---:|---:|---:|
| **Correct of 40** | **29** | **29** | **31** | **30** |
| Wrong values given | 0 | 1 | 5 | 5 |
| Correct abstentions (of 5) | 5 | 5 | 5 | 5 |
| Wrong abstentions | 11 | 10 | 4 | 5 |
| Gold chunk retrieved (of 35) | 24 | 24 | 29 | 29 |

Correct by kind:

| Kind | Questions | Plain | Design | Plain, per well | Design, per well |
|---|---:|---:|---:|---:|---:|
| Lookup in prose | 14 | 13 | 13 | 12 | 11 |
| Lookup in a table | 8 | 7 | 7 | 7 | 7 |
| Daily report | 4 | 1 | 1 | 2 | 2 |
| Conflict | 1 | 1 | 1 | 1 | 1 |
| Count | 1 | 1 | 1 | 1 | 1 |
| Comparison | 2 | 0 | 0 | 0 | 1 |
| Cross-report | 3 | 0 | 0 | 2 | 2 |
| Multi-hop | 2 | 1 | 1 | 1 | 0 |
| Must not answer | 5 | 5 | 5 | 5 | 5 |

Cost of answering, from the uncached repeats, with cost in dollars 0 because the runs are local:

| Per question | Plain | Design | Plain, per well | Design, per well |
|---|---:|---:|---:|---:|
| LLM calls | 1 | 1 | 1 | 1 |
| Prompt tokens, median | 1,438 | 1,580 | 3,117 | 3,407 |
| Prompt tokens, mean | 1,491 | 1,772 | 3,512 | 3,793 |
| Completion tokens, mean | 65 | 72 | 203 | 191 |
| Seconds, median | 0.97 | 0.99 | 2.22 | 2.37 |

- These figures leave out query embeddings and the dense index, which the ledger of an answer run does not count.
- **Cost per page to build the fact graph (E20, reused here):** 2.48 LLM calls, 4,749 prompt tokens, 314 completion tokens and 5.7 seconds. 29 of its 372 calls were cached, so the seconds are slightly low. Plain RAG has no LLM cost at index time, and table facts use no model call.

## Repeatability

Each setup was run a second time with `--fresh`. All 160 answers kept the same status, values and score. Completion tokens changed only in Design, per well (7,376 and 7,642), where the first run took 4 answers from the cache.

## What was learned

1. **The fact graph did not help on this set.** Top-5 setups tie at 29/40 with the same 11 questions missed. Per-well setups differ by one question (31 and 30). E22's gain over plain RAG on the 31 questions (30 against 28) does not appear here.
2. **The sheet rarely holds what is asked.** Only 4 of the 35 questions with gold (s02, s08, s15, s18) have their gold value in the validated sheet on a gold chunk. K2's facts have no rigs, people, companies, rotary Kelly bushing heights or casing grades. The check matches values exactly, so a comparison question whose inputs are in the sheet, such as s30, does not count.
3. **The sheet changed few answers, in both directions.**
   - Fixed by the sheet: s30, where Design, per well reads the three total depths and answers 68-32 (Plain, per well says AK-3).
   - Lost with the sheet: s22 and s35 (per well).
   - Made worse without changing the score: s33 (top 5) goes from an abstention to a wrong answer.
4. **The validator lets wrong facts through.** It checks that the value is in the chunk, not that the fact means what it says.
   - s33, the only wrong answer in Design, comes from the sheet: AK-3's *planned* 220 ft, and 933.22 ft for 68-32, which is a float collar depth. The citation check marked both answers unsupported, but this run did not use `--withhold-unsupported`.
   - All 13 of 68-32's kept `casing_depth` facts come from the LLM, and none gives the true 978 ft. Their casing "sizes" include `10031` (the rig number), `8.33` and `1-39` (a time-code column).
5. **The retrieval and answer setup matters more than the sheet, and it trades errors.** Per-well fusion with evidence first takes cross-report questions from 0/3 to 2/3 and retrieves more gold chunks. It also gives 5 wrong values against 0, at about 2.3 times the prompt tokens.
   - The wrong values include model errors on easy lookups: s16 returns `9` with the unit `March` for a date.
   - Most of the gain is on questions naming several wells. Using per-well only for those five questions (s29 to s33) and top 5 for the rest gives 31/40 with 1 wrong for plain and 32/40 with 0 wrong for the design. **These two figures are computed from the rows above, with the rule chosen after seeing them; they are not a run.**
6. **Abstaining is still the main failure in the top-5 setups.** 11 of the 16 abstentions in Plain are wrong, so the 5/5 on must-not-answer questions is weaker evidence than it looks.
7. **Daily reports need date routing.** 68-32 has 12 near-identical daily forms in the pool. s27 answers 9, the total personnel of 6 March, instead of 12 for 9 March. Filtering by well does not separate them. This goes into E24.

## Limits

- **One flawed gold value, kept because the set is frozen:** s02 expects 1.75°, from the report's prose. The report's own survey table ends with 2° at 1,900 ft, so the per-well answer of 2 is defensible. Scoring it as right adds one to both per-well setups and changes no conclusion. Fix it in the next version of the set.
- "Gold chunk retrieved" is generous on questions needing several chunks: any one of a fact's chunks counts. On s29, per-well retrieval counts as a hit without the 56-32 height (30.40) in any passage; top 5 has both heights, and the model still abstains. A correct answer can also come from another chunk holding the same value (s25).
- 40 questions on the reports the mappings were written from. Differences of one or two questions are noise.
