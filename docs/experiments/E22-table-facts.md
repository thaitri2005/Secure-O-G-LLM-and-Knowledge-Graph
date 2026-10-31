# E22: Facts from table rows by K2 mappings, combined with extracted facts

| | |
|---|---|
| **Date** | 1 November 2026 |
| **Question** | The LLM extractor misses mostly table rows (E20). Do deterministic table mappings, with no model call, raise fact recall, and do they help answers next to the extracted facts? |
| **Requirement** | §6.2 stage 4 (table mappings validated against the ontology), risk R-01 (deterministic table mapping), B-D19 |
| **Input** | K1 version 0, three-report pool; Docling tables in `data/processed/gdr_tables.jsonl` |
| **Code** | `graphrag/tables.py`; mappings in [`k2_eowr_v1.json`](../../configs/ontology/k2_eowr_v1.json) `table_mappings`; `baseline.py --fact-sheet <several> --validate` |
| **Gold data** | The prototype's 31 questions and 41 AK-3 facts; the 9-question probe |
| **Models** | Table facts: none. Extracted facts: E20's Qwen3-4B run. Answers: Qwen3-8B (thinking off), `-c 32768 -np 1`, one request at a time |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E22_*.json` |
| **Status** | Done |

## How the mappings work

- **Series tables:** a table whose headers contain the mapping's words as whole words (`inclination|inc` and a depth column; `projected` and `depth`; `casing` and `depth`) gives one fact per row, with the context column (depth or casing size) attached.
- **Row tables:** a first-column label such as "Total Productive Time" maps to a property; the value comes from the `hours` column.
- The well is the document's most-named well; the qualifier is `planned` when the caption says so ("Table 1: Planned AK-3 well configuration"); each fact cites the chunk holding its row (K1 chunks carry their table row range).
- A first version matched words as substrings, and "inc" matched "Hole (inches)", turning casing tables into surveys. Whole-word matching fixed it (11 casing facts instead of 3).

## Fact recall (41 AK-3 gold facts)

| Source | Model calls | Facts (three reports) | Recall raw | Recall after validation |
|---|---:|---:|---:|---:|
| LLM extraction (E20, Qwen3-4B) | 372 (2.5 per page) | 737 | 0.49 | 0.42 (96 kept) |
| **Table mappings** | **0** | 34 | **0.68** | 0.68 (32 kept) |
| Both | 372 | 771 | 0.88 | **0.78** (116 kept) |

The recall here counts a fact only with its well, qualifier and context; `neo4j_kg`'s own score (0.56 for the LLM run) matches more loosely.

## Answers with the validated fact sheet

| Fact sheet | 31 single-well questions (BM25 routed by well, top 5) | Probe (per-well fusion, top 10, evidence first) |
|---|---:|---:|
| None (D-50 baseline; E19) | 28/31 | 3/9 |
| LLM facts (E20) | 28/31 | 5/9 |
| Table facts only | 26/31 | 2/9 |
| **LLM and table facts** | **30/31** | 4/9 |

- With both sources the only single-well miss is q05 (27 days on the project, answered 19, the spud-to-release days). q07 (a date without a year), q25 and q31, the baseline's three misses, are now right.
- On the probe, the combined sheet answers p02, p03, p04 and p08; it loses p06 (a cover-page name, not a fact in the sheet), which the LLM-only sheet had answered.
- Table facts alone help less: the series (inclination, casing, rig time) are there, but the well-level values in prose (total depth, dates) come only from the LLM.
- Cost per question: about 2,000 to 2,200 prompt tokens on the single-well questions (baseline 1,465), from the sheet lines.

## What was learned

1. **Deterministic table mappings are the cheapest source of facts:** 0.68 recall with no model call, against 0.49 for the LLM extractor at 2.5 calls per page. The two are complementary; together and validated they reach 0.78.
2. **Baseline plus a validated fact graph from both sources answers 30/31,** the best result on the development questions (E10 prototype 23/31, D-50 baseline 28/31).
3. **Caveats:** the mappings were written while looking at the AK-3 tables, from which the gold facts also come; the rules are generic header words, but they must be checked on other reports. One run; 31 and 9 questions.
