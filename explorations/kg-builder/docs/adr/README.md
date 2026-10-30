# Design decisions

| Decision | Rationale and consequence |
| --- | --- |
| Local guarded model access | Route LLM calls through a loopback gateway and enforce socket guards. Reproduction fails on missing fixtures rather than falling back to inference. |
| Separate EDC environment | Pin incompatible upstream dependency stacks separately; communicate through subprocess contracts rather than modifying upstream source. |
| Exact replay requests | Preserve prompt bytes, schemas, few-shot examples and request parameters. Renamed paths may change declared metadata, not request keys. |
| JSON graph as authority | Keep portable graph data and provenance independent of a database. Neo4j and GraphML are optional projections. |
| Separate implementation, evidence and outputs | Keep code under `src`, small immutable evidence under `data` and `results`, and disposable generated trees under ignored `runs`. |
| Full and strict graph views | Preserve weak evidence flags in the full graph and expose strict filtering separately so recall and precision tradeoffs remain measurable. |
| Frozen annotation and scoring inputs | Use seals and exact equivalence proofs to prevent silent benchmark changes. Publication narrative changes are explicitly mapped and resealed. |

These decisions preserve reproducibility and inspectability. They do not imply that every upstream project is executed: some pinned repositories supply reference designs, prompts or metrics only. See [architecture](../architecture.md) and [NOTICE](../../NOTICE.md).
