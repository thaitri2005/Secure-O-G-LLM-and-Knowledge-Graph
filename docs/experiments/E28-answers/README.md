# E28 answers, side by side

Every question of E28 with the gold answer and each method's answer and result, for reading without the raw run files.

| File | Questions | Event graph | Plain RAG, daily reports | Plain RAG, all AK-3 docs |
|---|---|---:|---:|---:|
| [frozen_35.md](frozen_35.md) / [.csv](frozen_35.csv) | 35, frozen before the graph was built | 22/35 | 4/35 | 5/35 |
| [new_23.md](new_23.md) / [.csv](new_23.csv) | 23 new, frozen before the planner fix ran | 19/23 | 4/23 | 4/23 |

- **The questions are simulated and no drilling expert has reviewed them.** Gold is computed by code from the PDFs' text layer, independent of the parsed chunks.
- Result is `correct`, `wrong` (a wrong value), `incomplete` (no wrong value but not all of the gold) or `abstained`. Scoring is `graphrag/scoring.py`.
- Method, setup and costs: [E28 record](../E28-event-graph.md). Raw runs, with plans, citations and tokens per question: `graphrag/results/E28_*.json`.
- Regenerate with `python -m graphrag.compare_runs` (commands in its docstring).
