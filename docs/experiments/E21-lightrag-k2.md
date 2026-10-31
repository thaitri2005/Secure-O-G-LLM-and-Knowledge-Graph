# E21: LightRAG with the K2 ontology injected

| | |
|---|---|
| **Date** | 1 November 2026 |
| **Question** | Does injecting our ontology slice (K2 version 1) into LightRAG's extraction make its graph more precise and its answers better than LightRAG's generic defaults (E19)? |
| **Requirement** | §6.2 (ontology slice injected at extraction), D-49, B-D17, B-D18 |
| **Input** | K1 version 0, three-report pool (372 chunks, 150 pages) |
| **Code** | `graphrag/lightrag_run.py index --guidance data/interim/k2_eowr_v1_guidance.txt`; the guidance is `python -m graphrag.ontology guidance` (K2's 9 entity types with definitions and examples, its 13 relations, and a note to keep units and planned or actual), passed as LightRAG's `addon_params["entity_types_guidance"]` |
| **Gold data** | The prototype's 31 questions; the 9-question probe |
| **Models** | Qwen3-8B (thinking off) for extraction, keywords and answers, `-c 32768 -np 1`; Qwen3-Embedding-0.6B. The index shared the GPU with E20 and E22 runs on a second server, so its seconds are high |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E21_*.json` |
| **Status** | Done |

## Graph

| | LightRAG defaults ([E19](E19-lightrag.md)) | **With K2** |
|---|---:|---:|
| LLM calls (per page) | 777 (5.2) | 758 (5.1) |
| Tokens per page | 15,300 | 15,900 |
| Entities | 2,114 | **925** |
| Relations | 3,099 | **1,385** |
| Top entity types | artifact 463, data 343, concept 297, event 262 | well 123, other 108, document 87, hole section 69, formation 58, project 41, organization 37, casing string 29, person 26, rig 23 |
| Untyped (`UNKNOWN`) | 95 | 225 |

K2 halves the graph and gives it the domain's types at the same extraction cost. A quarter of the entities still come back untyped, and some types outside K2 appear (equipment, location, place).

## Answers

| Question set | LightRAG defaults (E19) | **With K2** | Plain RAG (D-50) | Working design (E22) |
|---|---:|---:|---:|---:|
| 31 single-well questions, `mix`, small budget | 25/31 | 26/31 | 28/31 | 30/31 |
| Probe, `mix`, small budget (evidence first) | 3/9 | 3/9 (p03, p05, p08) | 3/9 | 2 to 5 of 9 |
| Probe, `mix`, default budget (evidence first) | 1/9 | 4/9 (p02, p04, **p07**, p08) | — | — |

- With the default budget, LightRAG with K2 is the first setup to answer p07 (how many reports cover Utah FORGE wells: 2), from its document and project entities. It costs about 14,500 prompt tokens per question.
- On the single-well questions it still misses table values plain RAG reads (q09 API number, q18 rig time) and q07's year.

## What was learned

1. **Injecting the ontology works mechanically and cheaply:** the same extraction calls produce half the entities, typed by K2. This is the §6.2 injection point, through the base's own setting, with no fork of its code.
2. **It does not change the verdict:** LightRAG with K2 stays below plain RAG on single-well questions (26 against 28 of 31), and its probe scores are within the noise of B-F29.
3. **What it adds is document and project structure** (p05, p07), which the per-well fact graph of E22 lacks. If expert questions ask for those, LightRAG's K2 graph (or K2's Person, Project and Document types in our own extraction) is where they come from.
