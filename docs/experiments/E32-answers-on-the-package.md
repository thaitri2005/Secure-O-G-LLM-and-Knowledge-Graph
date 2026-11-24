# E32: Answers on the demo package, from files and from the stores

| | |
|---|---|
| **Date** | 25 November 2026 |
| **Question** | Does the system answer as well on the K1 package `demo-v2` as on the older chunks the first build was measured on, and does it answer from the stores? |
| **Requirement** | D-57 (K1 version 1 as the interface), D-65 (one connected application), plan tasks E1 and E2 |
| **Input** | The package `demo-v2` built on the run's machine from the public PDFs (release `20261124T185223Z-ccc792161833`: 8 files, 302 pages, 1,432 chunks; Track A log A-F22). The stores loaded from it by the runner: 1,432 vectors, 161 events, 207 facts (Track C log C-F09) |
| **Code** | `graphrag/baseline.py` (pool `k1_ak3`), `backend/`, `platform/run_release.py`, `deploy/smoke_test.py` |
| **Gold data** | The prototype's 31 questions on AK-3 with their gold facts (`prototype/gold/`), written by the team with AI; not expert-reviewed |
| **Models** | Qwen3-8B Q4_K_M, our own copy, llama.cpp b12015 CPU build (profile `qwen3-8b.cpu`), thinking off, one slot, 8k context, one request at a time. Qwen3-Embedding-0.6B for the vectors |
| **Outputs** | `graphrag/results/E32_cpu_k1_prototype.json`; the baseline beside it, `bench_qwen3-8b.cpu_quick_quick_prototype.json`; the stores' run row `demo-v2-20261124T190029Z` |
| **Status** | Done for the AK-3 report with plain retrieval, and for one question through the whole application. The full suite on the package (every question set, with `--k1`) is E33's run |

## Results

### The same 31 questions, old chunks and the package

BM25, top 5, AK-3's end-of-well report only, one answer call a question.

| Chunks | Correct | Answers with a wrong value | Prompt tokens a question | Seconds a question |
|---|---:|---:|---:|---:|
| K1 version 0, as in every recorded run (60 chunks) | 28/31 | 2 | 1,452 | 136 |
| The package, K1 version 1 (61 chunks) | 26/31 | 2 | 1,529 | 42 |

- Wrong in both: q07, q25, q31. Wrong only on the package: q11 and q12, the setting depths of two casing strings.
- **The two lost answers are not lost by retrieval.** The casing table that holds both values is among the five passages in both runs, at rank 1 or 3. On the package the model answers "not stated".
- The seconds differ because the first run shared the machine with other work; the tokens are comparable.

### Through the whole application, from the stores

The backend as a container, reading the package from PostgreSQL and the graph from Neo4j, behind the proxy and its password, with the same model. `deploy/smoke_test.py` from outside: 6 of 6 checks.

| | |
|---|---|
| Question | "What total depth did well AK-3 reach?" |
| Answer | 1955 ft, from well facts and passages, cited to the package's chunk on page 7 of AK-3's report |
| Cost | 2 calls, 3,544 prompt and 200 completion tokens, 212 seconds while the machine was shared |
| Search for questions naming several wells | Chosen at start: BM25 fused with the vector search inside PostgreSQL, on 1,432 stored vectors |
| Written to | The question log in PostgreSQL, with its mark |

## What was learned

1. **The package costs two answers of 31 on this set, and the cause is the model's reading of one table, not the search.** The casing table is found either way. Its text differs between the two chunk versions, and Qwen3-8B abstains on the newer one. This is the table Track A's options change (plan task D2), so it is the first thing to look at when those are measured.
2. **The application answers from the stores with the real model.** Every part was exercised by one question: the proxy, the backend, the coordinator, the well facts from Neo4j, the passages from PostgreSQL, the checks, the question log.
3. **The first real answer showed a fault no test had:** "1955 in", from "1,955 in contrast to". The unit is now checked against the cited passage (Track B log B-F76, B-F78).
4. **Vector search in the database works on real vectors:** 67 of 67 check searches return what the search in memory returns.

## Limits

- **One report, 31 questions, plain retrieval.** The other question sets, the fact sheet and the coordinator on the package are in E33's run.
- **One question through the application** is a check that the parts connect, not a score.
- **The package differs by one chunk from the one built on the laptop** (1,432 against 1,431, in the 68-32 report), so this record names its release.
- The questions are the team's, not an expert's.
