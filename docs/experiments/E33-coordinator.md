# E33: The coordinator against choosing the lane by hand

| | |
|---|---|
| **Date** | 25 November 2026 |
| **Question** | With no lane given, does the coordinator (specification §8.1) answer as well as the runs where a person chose where to look, and at what cost? That is the adoption test of D-64 |
| **Requirement** | D-58, D-64 |
| **Input** | The K1 package `demo-v2` built on the run's machine (release `20261124T185223Z-ccc792161833`, 1,432 chunks); the event graph built from it (161 events); the fact graph (207 facts) |
| **Code** | `graphrag/coordinator.py`, `graphrag/lanes.py`; `python -m graphrag.coordinator answer --questions prototype ak3_daily ak3_events ak3_events_heldout --k1 --no-embeddings --name E33_cpu_coordinator_pool` |
| **Gold data** | One question set per lane, 119 questions, **all written by the team and none reviewed by a drilling expert**: `prototype` (31, end-of-well), `ak3_daily` (30, daily reports), `ak3_events` (35) and `ak3_events_heldout` (23, totals over time) |
| **Models** | Qwen3-8B Q4_K_M, our own copy, on llama.cpp b12015's CPU build (profile `qwen3-8b.cpu`), thinking off, one slot, 8k context, `--cache-ram 0`, one request at a time |
| **Outputs** | `graphrag/results/E33_cpu_coordinator_pool.json`; earlier passes `E33_cpu_coordinator_events_first_run.json`, `E33_cpu_coordinator_events.json`, `E33_cpu_coordinator_ak3_daily_first_run.json`, `E33_cpu_coordinator_partial.rows.txt`; hand-routed `bench_qwen3-8b.cpu_full_hand_prototype.json`, `bench_qwen3-8b.cpu_full_hand_ak3_daily.json`, `E33_cpu_hand_ak3_events.json`, `E33_cpu_hand_ak3_events_heldout.json` |
| **Status** | Done on one set per lane. The other three sets (102 questions) were not run: the team stopped measuring on its own questions on 25 November, until an expert's set exists ([how it comes in](../EXPERT_PILOT.md)) |

## Results

Hand-routed: a person chose the lane per question set, and the baseline was rerun on the same machine.

| Question set | Questions | Hand-routed | Coordinator | Routed as by hand |
|---|---:|---:|---:|---:|
| `prototype` (end-of-well) | 31 | 29 | 28 | 25 |
| `ak3_daily` (daily reports) | 30 | 17 | 16 | 27 |
| `ak3_events` (totals over time) | 35 | 25 | 34 | 30 |
| `ak3_events_heldout` | 23 | 16 | 23 | 19 |
| **All** | **119** | **87** | **101** | **101** |

Whole numbers are scored exactly. The run was recorded as 102: one daily answer of 1,160 ft for a gold of 1,165 passed the 0.5% the scorer then allowed (Track B log B-F85). No hand-routed score changes.

### Cost per question

| | Calls | Prompt tokens | Completion tokens | Seconds on this CPU |
|---|---:|---:|---:|---:|
| Hand-routed, all 119 | 1.5 | 2,447 | 127 | 82 |
| Coordinator, all 119 | 1.5 | 2,266 | 158 | 72 |
| Hand-routed, end-of-well lookup | 1.0 | 1,678 | 82 | 47 |
| Coordinator, end-of-well lookup | 1.8 | 2,802 | 172 | 83 |
| Hand-routed, daily lookup | 1.0 | 1,858 | 59 | 52 |
| Coordinator, daily lookup | 2.0 | 3,071 | 199 | 117 |
| Hand-routed, total over time | 2.0 | 3,161 | 185 | 115 |
| Coordinator, total over time | 1.2 | 1,564 | 129 | 44 |

US$0 on our own copy. On a GPU that answers a lookup in a second, every figure in the last column is a few seconds.

### The passes before the last one

| Pass | What it showed | Score |
|---|---|---|
| Event questions, coordinator as built | 14 of 58 plans wrong in ways the question shows (an invented code, a field name as a code, a wrong year) | 44/58 |
| Event questions, plan checked in code | Those 14 caught | 58/58 |
| Daily questions, with that plan check | The check called every dated lookup a question over time. The events lane then reported the day's depth, 770, for the inclination, the casing depth and a bit | 13/30 |
| Last pass: a question naming one day stays a lookup; a text that asks nothing does not reach the events lane | Daily back to one answer below the hand-routed score; one event question lost (t13) | 101/119 |

## What was learned

1. **The coordinator beats the hand-routed score on totals over time and is one answer short on end-of-well lookups and on daily lookups.** It costs the same number of calls overall: it saves a call on every total and spends one more on every lookup.
2. **The gain on totals is code reporting the number.** All 17 hand-routed losses on the event sets were the answer call retyping a computed number wrongly; the plans were right.
3. **The lookup costs one more call and buys nothing on these questions.** That is the price of not being told the lane.
4. **Five end-of-well questions go to the events lane** ("How many days did the project take?", "How much non-productive time was recorded?"). Three come out right from the daily reports, two wrong: "planned to take" (events hold what happened, not what was planned) and "productive hours" (the plan filtered on a code). The hand-routed run got one of the five wrong. Both sources hold these answers; the coordinator has no rule for which to prefer.
5. **Three daily lookups were framed as "other" and searched in the end-of-well report** (sacks of cement, inventory units, a serial number): 3 of the 14 daily losses. One more is a depth gain computed 5 ft short. The other 10 are lost by the hand-routed run too.
6. **Every fault found was the model's frame against what the question plainly says, or our own rule being too broad.** Each fix is a check in code, and the second fault was introduced by the first fix. A rule tuned on one set has to be run on the others before it is trusted.
7. **An injected instruction reached the events lane and got a number** ("Ignore all previous instructions…" answered 647.5 hours) in the stopped run, because code reports a computed result without the model reading the question again. It now goes to passages and is answered "not stated".

## Decision (D-64)

The coordinator stays the application's path, and the hand-routed commands stay as the baseline to compare with. It is well above the hand-routed score on totals over time and one answer below on each kind of lookup, at the same cost.

This is not the adoption test passed in full: the checks were written while looking at these 119 questions, and 102 other questions were not run. The test that counts is an expert's question set, run once through both paths.

## Limits

- **Questions written by the team.** Not an evaluation.
- **Tuned on what it is scored on.** The plan checks were written from the event sets' misses and the one-day rule from the daily set's. Only `ak3_events_heldout` under the first plan check (18/23 as built) was unseen.
- **Three sets not run** (`simulated`, `heldout`, `ak3_daily_heldout`). A stopped run answered 14 `simulated` questions, 10 right against 13 hand-routed; two of the four misses were routing.
- **CPU timings**; token counts are exact. Framing calls of the last pass came from the request cache, and their recorded seconds are counted.
