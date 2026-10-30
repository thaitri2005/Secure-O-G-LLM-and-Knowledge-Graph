# E16: neo4j-graphrag-python on the AK-3 end-of-well report

| | |
|---|---|
| **Date** | 31 October 2026 |
| **Question** | Does the first candidate base, neo4j-graphrag-python, extract the gold facts with a small open model, at what cost per page, and do its facts help answers? (Track B, B-D04, B-D10 step 2) |
| **Requirement** | D-36, D-37, D-41, D-44; Track B decisions B-D04, B-D08, B-C01 to B-C04 |
| **Input** | K1 version 0 chunks, AK-3 pool (60 chunks, 28 pages), passed to the library unchanged. Ontology: `prototype/profiles/oil_wells.json` (14 properties) |
| **Code** | [`graphrag/neo4j_kg.py`](../../graphrag/neo4j_kg.py); answers through `graphrag/baseline.py --facts`. Neo4j 5.26 with APOC from [`configs/graphrag/docker-compose.yml`](../../configs/graphrag/docker-compose.yml). Library environment: `requirements-graphrag.lock.txt` |
| **Library** | neo4j-graphrag 1.23.0 (Apache-2.0), used as a dependency; no code copied |
| **Gold data** | The prototype's 41 gold facts and 31 questions, unchanged |
| **Models** | Qwen3-4B-Instruct-2507 Q4_K_M and Qwen3-8B Q4_K_M (thinking off) for extraction and answers; Qwen3-Embedding-0.6B Q8_0 for the library's chunk embeddings. llama.cpp b12015 on the desktop GPU (RTX 4080 SUPER), `-c 32768 -np 4` |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E16_graph_{library,domain,context}_qwen3-4b.json`, `E16_graph_library_qwen3-8b.json`, `E16_answers_{control,facts}_qwen3-4b.json`, `E16_answers_facts_qwen3-8b.json` |
| **Status** | Done for extraction and for facts-as-context answers. The library's own retrievers (vector-Cypher, Text2Cypher) were not run |

## Setup

- **Schema from the ontology file.** Properties without context (total depth, dates, rig times and so on) become `Well` properties, with `planned_` versions where the profile allows a planned value. Properties with context become linked node types: `CasingDepth` (with casing size), `Inclination`, `MaxMeasuredTemperature` and `ProjectedFormationTemperature` (with depth), each linked by `HAS_<PROPERTY>` from `Well`. Undefined node types, relationships, patterns and properties are pruned.
- **Our client as the library's LLM and embedder**, so every call is cached, counted and guarded; structured output is switched on (the library's `use_structured_output`, sent as a JSON-schema request).
- **The K1 chunks pass through unchanged**, so every extracted node links to a chunk we can cite. Entity resolution is off, so each fact keeps its chunk.
- **One request at a time** (`--concurrency 1`). With 4 parallel requests the results were not repeatable (see below).
- **Scoring.** Recall: a gold fact is found if any extracted fact has the same well, property, qualifier, context and a matching value. "Right where keyed": of the extracted facts whose key exists in the gold set, the share with the right value. This is a precision proxy; facts with keys outside the gold set are not judged. E10's precision was computed differently, so compare only roughly.

Three prompts were tried with the 4B model:

| Prompt | What it is |
|---|---|
| `library` | The library's default `ERExtractionTemplate`, unchanged |
| `domain` | The library's format and schema with the E4 prompt's domain rules (default well, value only, contexts required, planned versus actual, every table row, no guessing), rewritten for nodes |
| `context` | The library's default with one added sentence: the report is about AK-3, unnamed tables are about AK-3, wells are named like AK-3, TG-2, TG-4 |

## Run-to-run variation

The same build, three cold runs each:

| Prompt | 4 parallel requests: recall | 1 request at a time: recall |
|---|---|---|
| library | 0.54, 0.85, 0.85 | 0.854, 0.854, 0.854 |
| domain | 0.51, 0.46, 0.51 | 0.439, 0.439, 0.439 |

llama.cpp batches parallel requests together, and the batch composition changes the numerics; over long JSON outputs this snowballs. One request at a time is bit-for-bit repeatable. All numbers below are from single-request runs.

## Extraction

| Model | Prompt | Recall (41 facts) | Right where keyed | Facts extracted | Seconds | Per page: calls, prompt tokens, output tokens, seconds |
|---|---|---:|---:|---:|---:|---|
| Qwen3-4B | library | **0.854** | 0.72 (49/68) | 114 | 83 | 2.1, 4,070, 406, 3.0 |
| Qwen3-4B | domain | 0.439 | **0.84** (27/32) | 69 | 65 | 2.1, 4,610, 295, 2.3 |
| Qwen3-4B | context | 0.366 | 0.45 | 175 | 145 | 2.1, 4,224, 804, 5.2 |
| Qwen3-8B | library | 0.512 | 0.38 | 255 | 208 | 2.1, 4,079, 784, 7.4 |
| *E10 prototype, Qwen2.5-3B, own pipeline (for reference)* | | *0.732* | *0.968 (different definition)* | | | |

- Calls per page are 2.1 because the 60 chunks sit on 28 pages; there is one extraction call per chunk and no other LLM call. The chunk embeddings add 11,001 tokens in about 10 s.
- Invalid JSON: 0 in every 4B run, 1 of 60 in the 8B run.
- **Library prompt, 4B.** It misses six facts: the rig-time table (g39 to g41, put on a well it named `Well_A`), TG-4's depth (g04), spud-to-release days (g07) and one casing row (g15). It reads the whole survey table. Its 19 wrong keyed facts include made-up values such as an inclination of 5° at 1,000 ft copied onto three wells.
- **Domain prompt.** More precise but far less complete: it skips the survey table entirely (13 facts) and the casing tables. The extra rules make the 4B model abstain, the same failure E14 saw in the answer step.
- **Context prompt.** One added sentence made the model put nothing on the `Well` node and invent a reading of every measurement type for each chunk.
- **Qwen3-8B** extracts more and worse: 255 facts, most of them guesses, and it also misses the survey table.

## Answers with the extracted facts

The E15 setup (BM25, top 5, the same answer prompt) with each passage followed by the facts extracted from it. The control is the plain E15 setup rerun on the same server settings.

| Model | Context | Correct | Answerable | Answers with no wrong value | Prompt tokens |
|---|---|---:|---:|---:|---:|
| Qwen3-4B | passages (control) | **23/31** | 12/18 | 16/18 | 44,876 |
| Qwen3-4B | passages + library facts | 21/31 | 10/18 | 13/14 | 57,715 |
| Qwen3-8B | passages ([E17](E17-model-sweep.md)) | **28/31** | 17/18 | 21/23 | 45,000 |
| Qwen3-8B | passages + 8B facts | 28/31 | 16/18 | 20/22 | 58,388 |

- With the 4B model, the facts made it abstain on questions it answered without them, including the simplest (q01 and q02, total depth). Contradicting facts are the likely cause.
- With the 8B model they change which questions are right, not how many, for 30% more prompt tokens.
- The control scored 23/31 against 22/31 in E15 with the same requests: changing the server settings (context size and slots) changes decoding. Differences of one or two questions remain noise.

## What was learned

1. **The library works as a base:** schema injection, pruning, chunk provenance and structured output all behaved as documented, at about 2 calls and 4,500 tokens per page, with no invalid JSON on the 4B model.
2. **Extraction quality from small models is fragile.** One sentence of prompt moved recall from 0.85 to 0.37, and the 8B model was worse than the 4B. Tuning prompts against 41 gold facts would overfit; a larger, held-out fact set is needed before prompt work is worth it.
3. **On this report and these questions, a graph built this way does not help answers.** Plain retrieval with Qwen3-8B already answers 28/31; adding about 28% wrong facts to the context costs tokens and, with the 4B model, answers.
4. **Run settings are part of the result.** Parallel requests must be off for measurements, and server settings must be recorded with each run.

## Not done

- The library's own retrieval (vector-Cypher, hybrid, Text2Cypher) and its `GraphRAG` answer class.
- Entity resolution (APOC is installed; it was left off to keep each fact on its chunk).
- Extraction on the three-report pool.
