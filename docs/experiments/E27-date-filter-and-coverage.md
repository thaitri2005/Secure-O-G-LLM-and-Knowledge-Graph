# E27: Date filter for daily reports, and more fact-graph coverage

| | |
|---|---|
| **Date** | 4 November 2026 |
| **Question** | (1) E24 found retrieval cannot tell the days of one well apart. Does filtering by report date fix that on unseen questions? (2) E23 found the fact sheet rarely holds what is asked. Does adding casing weight, grade, rig and contractor help? |
| **Requirement** | B-F31, B-F35, B-D21 |
| **Input** | (1) The four AK-3 daily-report attachments, 898 chunks. (2) K1 version 0, three-report pool |
| **Code** | `graphrag/retrieval.py` (`DateRouter`, `page_dates`), `dates:<retriever>`; `graphrag/tables.py`, K2 version 1.1 (`casing_specs`, `key_value`) |
| **Gold data** | (1) [`ak3_daily_heldout_v0.json`](../../graphrag/gold/ak3_daily_heldout_v0.json): 26 questions on three days E24 did not use, written from the rendered pages and frozen before any run. **Simulated: no drilling expert has reviewed it.** (2) The sets of E26, all already seen |
| **Models** | Qwen3-8B (thinking off), `-c 32768 -np 1 -ngl 99`, one request at a time |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E27_*.json`; K4 records in `E27_heldout_dates_bm25.k4.jsonl` |
| **Status** | Done |

## Part 1: date filter

`page_dates` gives each page its report date, in order of preference:

1. A `Report For` line on the page.
2. The date another attachment gives the page's `Report No`, for pages whose header lost the date in parsing.
3. The date of the page before, for continuation pages.

It is a stand-in until K1 version 1 carries report dates. Checked against the text layer of the PDFs, it dates **143 of 145 pages correctly**, and all 898 chunks get a date (268 had one in E24). The two wrong pages are report 7 in attachments 29 and 30. The parser gives the first chunk of attachment 30's page 7 the previous day's section title, `page_dates` trusts the first date it finds on a page, and attachment 29 then inherits the wrong date through its report number. So the error is partly ours. No question uses that day. Fixed in [E28](E28-event-graph.md): 145 of 145.

Results on the 26 unseen questions:

| Setup | Correct | Wrong values | Wrong abstentions | Prompt tokens, median | Completion tokens, median | Seconds, median |
|---|---:|---:|---:|---:|---:|---:|
| BM25, top 5, status first (E24's plain) | 7 | 3 | 16 | 1,374 | 21 | 0.54 |
| **Date filter, BM25, top 5, status first** | **14** | **2** | 10 | 2,169 | 44 | 0.91 |
| Date filter, top 5, evidence first | 16 | 5 | 5 | 2,227 | 219 | 2.35 |
| Date filter, top 10, evidence first | 17 | 6 | 3 | 4,282 | 221 | 2.87 |

All setups have 1 LLM call per question and cost $0 (local). The filter itself needs no model call and no embedding.

| Kind | Questions | No filter | Filter, status first | Filter, top 5, evidence | Filter, top 10, evidence |
|---|---:|---:|---:|---:|---:|
| Form header | 6 | 1 | 4 | 4 | 5 |
| Operations table | 4 | 1 | 3 | 4 | 4 |
| Survey table | 2 | 1 | 2 | 2 | 2 |
| Mud table | 3 | 1 | 2 | 2 | 2 |
| Bit table | 3 | 0 | 0 | 1 | 1 |
| Drilling parameters | 2 | 0 | 0 | 0 | 0 |
| Inventory | 1 | 0 | 0 | 0 | 0 |
| Across days | 2 | 0 | 0 | 0 | 0 |
| Must not answer | 3 | 3 | 3 | 3 | 3 |

On E24's 30 questions, already seen when the filter was written: 5, 12, 17 and 21, with 2, 3, 7 and 7 wrong values.

**This corrects a sentence in E24.** E24 said the right-page diagnostic (19/30) bounds what better retrieval alone could reach. 21/30 exceeds it, because the filter can show the same day's copies from several attachments, where the diagnostic gave one page. One copy may parse better than another: attachment 28 keeps `Air Temperature: 58 degF`, which attachment 30 loses.

## Part 2: fact-graph coverage

K2 version 1.1 adds two properties (`rig`, `drilling_contractor`) and two mappings, for 24 new facts with no model call. All 24 were checked by eye against the source tables: 12 casing weights, 10 casing grades, one rig and one contractor. Existing facts did not change.

| Setup | Held-out 36 | Simulated 40 | Prototype 31 |
|---|---:|---:|---:|
| Plain, routed | 23 (7 wrong) | 31 (1 wrong) | 28 (2 wrong) |
| Fact sheet, routed, strict (E26) | 23 (7 wrong) | 31 (1 wrong) | 31 (0 wrong) |
| **With the added coverage** | 23 (6 wrong) | 31 (1 wrong) | 30 (1 wrong) |

**The added coverage changes nothing measurable.** Against E26's sheet it gains h16 and loses h32 and q05. All these sets were seen before the mappings were written, and even so there is no gain.

An example of why: s14 asks for the grade of the "production casing" of 56-32. The sheet now holds `L-80` for the 5-1/2 in. casing, but nothing tells the model that the production casing is the 5-1/2 in. string.

LLM extraction was not rerun with more properties. It costs 2.48 calls per page, and nothing here suggests it would pay for them.

## What was learned

1. **Filtering by report date is the biggest gain found on daily reports:** it doubles the score on unseen questions, reduces wrong values, needs no model, and costs about 800 more prompt tokens per question.
2. **More recall costs wrong values.** Evidence first with top 10 reaches 17/26 with 6 wrong against 14/26 with 2. In a drilling application a wrong number is worse than "not stated", so status first stays the default for daily reports.
3. **Drilling parameters, inventory and across-days questions stay at zero,** consistent with E24: they need the structure Track A was asked for, and across-days also needs arithmetic.
4. **Adding facts to the sheet does not by itself improve answers.** Together with E23 and E26, this means that on the questions we have, the fact graph has not earned its place in the baseline.

## Limits

- Three days of 27, written by the filter's author after seeing E24's results.
- Each setup was run once. E24's d20 shows a daily-report answer can change between runs.
- "Gold day retrieved" reaches 23/23 with the filter by construction, because gold is defined as the day's pages. It does not show that the value reached the model.
- `page_dates` assumes one well's reports in the pool when it matches report numbers, and it reads only this form's `Report For` and `Report No` labels. Other report series will need K1 version 1's report date.
- The questions write full dates ("4 September 2016"). Other forms, such as "Sept 4" or "the day after spud", are not filtered and fall back to unfiltered retrieval.
