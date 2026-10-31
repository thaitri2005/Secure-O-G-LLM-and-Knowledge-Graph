# E20: Extracted per-well facts as answer context

| | |
|---|---|
| **Date** | 1 November 2026 |
| **Question** | Questions across wells need each well's values (E19). Does a graph of per-well facts, extracted once and looked up for every well a question names, help the answers? |
| **Requirement** | D-36, D-50; Track B B-D15 |
| **Input** | K1 version 0, three-report pool (372 chunks, 150 pages) |
| **Code** | `graphrag/neo4j_kg.py` (neo4j-graphrag-python 1.23, library prompt, the prototype's 14-property profile, unchanged); `graphrag/baseline.py --fact-sheet` (facts of each named well, well-level facts first, at most 25 lines per well, each with its source chunk) |
| **Gold data** | The prototype's 31 questions and 41 facts; the 9-question probe |
| **Models** | Extraction: Qwen3-4B-Instruct-2507 Q4_K_M on a second llama-server (port 8082, `-c 16384 -np 1`). Answers: Qwen3-8B (thinking off, `-c 32768 -np 1`). One request at a time per server; both servers shared the GPU with other runs, so seconds are not comparable |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E20_graph_three_qwen3-4b.json`, `E20_*_sheet.json` |
| **Status** | Done |

## Extraction

| | Three reports (this run) | AK-3 only ([E16](E16-neo4j-graphrag-python.md)) |
|---|---:|---:|
| LLM calls per page | 2.5 | about 2 |
| Prompt tokens per page | 4,749 | about 4,500 |
| Facts extracted | 737 | — |
| Recall of the 41 AK-3 gold facts | 0.56 (three fresh runs) | 0.85 (not reproduced) |
| Right where gold has the key | 47% | 72% |

- The same library prompt and model gave much lower AK-3 recall here. Two follow-up runs on AK-3 alone, with no cache, gave 0.561 again under `-c 16384 -np 1` and under E16's own `-c 32768 -np 4` (`E20_graph_ak3_*.json`): neither the pool nor the server settings explain it. The prompts are identical to E16's (113,964 tokens); only decoding differs, and most of the gap is one survey table. A second fresh three-report run gave the same 737 facts, so runs are repeatable today; E16's 0.854 is the figure that cannot be reproduced (B-F27, correcting B-F26). Pooling the two runs before validation changes nothing.
- The 68-32 report's daily-report tables produce junk: 364 of 737 facts are about 68-32, including `api_number = 10031` (a job number) on 11 chunks. Well names also come back in many forms (`68-32 26S 9W`, `Akutan Well AK-3`).

## Answers with the fact sheet

| Question set | Retrieval | Without sheet | **With sheet** | Prompt tokens (median), with sheet |
|---|---|---:|---:|---:|
| 31 single-well questions | BM25 routed by well, top 5, status first | 28/31 (E18) | **21/31** | 2,179 |
| 9-question probe | Per-well fusion, top 10, evidence first | 3/9 (E19) | **1/9** | 6,541 |

- Conflicting extracted values mislead the model: for q08 it answered three rig-release dates (2016-09-05, 2016-09-01 and 2019-03-12), and for q23 it gave a TG-2 spud date that no passage states. It abstained on q12, q16, q18 and q20, which it answers without the sheet.
- On the probe, the sheet did not turn depths into well names (p01, p04) and cost p03 and p06.

## Validated facts (`--validate`, `graphrag/validate.py`)

The same 737 facts, checked in code before they reach the answer model. A fact is kept only if its value is written in its source chunk, its well name resolves to one well that its own document names, it is not a zero (empty daily-report form fields), and no equally supported different value exists for the same well, property, qualifier and context (majority wins; a tie drops the key).

| Rejection reason | Facts |
|---|---:|
| Value not in its chunk | 146 |
| Zero value | 134 |
| No single well name (`Bows`, `8-3/4 in. hole`, `Well_0`) | 128 |
| Outvoted by a better-supported value | 98 |
| Tie between different values | 29 |
| Well not named in its document | 28 |
| **Kept** | **96** |

The validated AK-3 sheet carries the right total depth (1,955 ft, planned 1,700), spud and release dates, API number and ground elevation; noise remains in casing contexts and in 68-32's dates.

| Question set | Retrieval | No sheet | Raw sheet | **Validated sheet** |
|---|---|---:|---:|---:|
| 31 single-well questions | BM25 routed by well, top 5, status first | 28/31 | 21/31 | **28/31** |
| 9-question probe | Per-well fusion, top 10, evidence first | 3/9 | 1/9 | **5/9** |

- Probe answers right with the validated sheet: p02 (all three depths), p03, **p04 (now with well names)**, p06, p08. Still wrong: p01 (depth instead of name), p05 (a person across reports: not in the 14-property profile), p07 (a count of reports), p09 (68-32's spud date is wrong in the sheet).
- On the 31 questions the total holds, with different misses: q05, q18, q21 instead of q07, q25, q31.
- The cost is the extraction (2.5 calls and 4,750 prompt tokens per page with Qwen3-4B) and about 700 more prompt tokens per question that names a well; validation itself makes no model call.

## What was learned

1. **Extracted facts are a liability unless they are validated.** Raw, at 47% precision, they lower answers from 28 to 21 of 31. Validated in code, they keep 28/31 and lift the cross-report probe from 3/9 to **5/9**, the best of any setup so far (E19: plain RAG and LightRAG at 3/9). This is the first evidence that graph facts help on questions across wells.
2. **Daily-report tables are the main source of junk,** and they need Track A's table work before extraction.
3. **Caveats:** one run, 9 probe questions written by the team, AK-3 recall of the extractor only 0.56. Repeat on the expert question set before choosing.
