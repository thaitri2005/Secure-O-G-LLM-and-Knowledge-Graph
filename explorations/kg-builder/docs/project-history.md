# Development history

The first integrations established that upstream extraction and canonicalization could run through a local guarded service. EDC on ten WebNLG documents reached strict F1 about 0.843; KGGen with recorded MINE judging answered 29 of 45 queries correctly. These small runs validated integration and exposed dependency constraints, motivating separate pinned environments and exact request replay.

A configuration router then made KGGen, EDC and automatic selection interchangeable. The early combined KGGen configuration reached WebNLG strict F1 about 0.590, below standalone EDC. Combining components did not automatically improve quality: extraction errors, evidence handling and canonicalization interacted. The result motivated explicit stage outputs and ablation levels.

Evidence grounding and temporal provenance made graph statements auditable. JSON became the authoritative graph representation, with Neo4j as an optional projection. Exact offsets and source identities were checked at the contract boundary, so export and visualization could not silently drop provenance.

Graph QA added a second view of quality. In the sentence configuration, graph answer F1 fell from about 0.636 at extraction to 0.476 after validation and 0.390 after judging, while text retrieval scored about 0.736. Canonicalization, entity merges and fact ordering changed retrieval paths. Removing an incorrect edge could also remove a useful route to evidence; extraction accuracy and retrieval utility needed separate measurement.

Schema induction, evidence judging and the A0-A5 ablation ladder exposed these interactions. Earlier judge outputs suffered from truncated responses and mismatched boolean parsing. Numeric name collisions revealed a resolution weakness. Abbreviation-aware sentence boundaries, evidence windows, number guards, soft validation and evidence-based judging addressed these seams. The window configuration restored WebNLG EDC strict F1 to about 0.843 and reached graph QA F1 about 0.676, still below text-only retrieval on this sample.

BSEE table ingestion established deterministic source identities and large graph aggregates without an LLM. Narrative extraction then introduced typed well-operation values and an LLM-annotated benchmark. Evaluation corrections aligned the tooling with the frozen annotation guideline, including dates, units, status phrases and symmetric agreement. The labels remained distinct from expert ground truth.

Stage attribution identified extraction omissions as a major development-set loss. Guided extraction improved v1 test full-export L2 F1 from about 0.209 to 0.345, but the paired interval crossed zero and the pre-registered improvement was not confirmed. The larger benchmark compared guided extraction with windows, relation groups and a recall pass on development data. The selected recall configuration improved v2 test L2 F1 from about 0.453 to 0.501; its primary interval also crossed zero, so this improvement was not confirmed.

The release preserves these results, failures and measurement limits. It supplies immutable expected values, recorded responses, gold verification and field-specific publication mappings. Exact values, confidence intervals and scope-matched IAA are in [results](results.md). Different corpus and converter versions prevent direct v1-versus-v2 score comparisons.
