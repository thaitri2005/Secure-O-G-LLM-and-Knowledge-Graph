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
| Recall of the 41 AK-3 gold facts | 0.56 | 0.85 |
| Right where gold has the key | 47% | 72% |

- The same library prompt and model gave much lower AK-3 recall here. Differences: the pool (three reports in one build), the server (`-c 16384` on a second port). B-F19 and B-F20 already showed this extractor is fragile; this run does not separate the causes.
- The 68-32 report's daily-report tables produce junk: 364 of 737 facts are about 68-32, including `api_number = 10031` (a job number) on 11 chunks. Well names also come back in many forms (`68-32 26S 9W`, `Akutan Well AK-3`).

## Answers with the fact sheet

| Question set | Retrieval | Without sheet | **With sheet** | Prompt tokens (median), with sheet |
|---|---|---:|---:|---:|
| 31 single-well questions | BM25 routed by well, top 5, status first | 28/31 (E18) | **21/31** | 2,179 |
| 9-question probe | Per-well fusion, top 10, evidence first | 3/9 (E19) | **1/9** | 6,541 |

- Conflicting extracted values mislead the model: for q08 it answered three rig-release dates (2016-09-05, 2016-09-01 and 2019-03-12), and for q23 it gave a TG-2 spud date that no passage states. It abstained on q12, q16, q18 and q20, which it answers without the sheet.
- On the probe, the sheet did not turn depths into well names (p01, p04) and cost p03 and p06.

## What was learned

1. **Extracted facts are a liability unless they are precise.** At 47% precision, a fact sheet lowers answers from 28 to 21 of 31; E16 found the same direction at 72% precision. Graph facts should reach the answer model only after validation (§6.2 stage 6: verbatim value, unit and well checks, dropping contradictions) or only for review.
2. **Daily-report tables are the main source of junk,** and they need Track A's table work before extraction.
3. **Free-form extraction under the 14-property profile does not give clean per-well facts at this model size.** The next tests are K2 injected into LightRAG (E21) and stricter validation of extracted facts before use.
